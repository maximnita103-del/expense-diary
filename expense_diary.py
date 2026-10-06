"""Дневник личных расходов — десктопное приложение.
Python 3.8+, только стандартная библиотека (tkinter, sqlite3). Запуск: python expense_diary.py
Данные хранятся в файле diary.db рядом со скриптом.
"""
import csv
import os
import sqlite3
import tkinter as tk
from calendar import monthrange
from datetime import date, datetime
from tkinter import filedialog, messagebox, simpledialog, ttk

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diary.db")
COLORS = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
          "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"]
DEFAULT_CATEGORIES = ["Продукты", "Транспорт", "Жильё", "Развлечения", "Здоровье", "Прочее"]


# ---------------------------------------------------------------- данные ----
class Db:
    def __init__(self, path=DB_PATH):
        self.c = sqlite3.connect(path)
        self.c.execute("PRAGMA foreign_keys = ON")
        self.c.executescript("""
            CREATE TABLE IF NOT EXISTS categories(
                id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS operations(
                id INTEGER PRIMARY KEY, date TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                category_id INTEGER NOT NULL REFERENCES categories(id),
                comment TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS budgets(
                category_id INTEGER PRIMARY KEY REFERENCES categories(id) ON DELETE CASCADE,
                limit_amount REAL NOT NULL);
        """)
        if not self.c.execute("SELECT 1 FROM categories").fetchone():
            self.c.executemany("INSERT INTO categories(name) VALUES(?)",
                               [(n,) for n in DEFAULT_CATEGORIES])
        self.c.commit()

    def categories(self):
        return self.c.execute("SELECT id, name FROM categories ORDER BY name").fetchall()

    def add_category(self, name):
        self.c.execute("INSERT INTO categories(name) VALUES(?)", (name,))
        self.c.commit()

    def delete_category(self, cid):
        used = self.c.execute("SELECT COUNT(*) FROM operations WHERE category_id=?", (cid,)).fetchone()[0]
        if used:
            raise ValueError(f"В категории есть операции ({used}). Сначала удалите или перенесите их.")
        self.c.execute("DELETE FROM categories WHERE id=?", (cid,))
        self.c.commit()

    def set_limit(self, cid, limit):
        if limit <= 0:
            self.c.execute("DELETE FROM budgets WHERE category_id=?", (cid,))
        else:
            self.c.execute("INSERT INTO budgets(category_id, limit_amount) VALUES(?,?) "
                           "ON CONFLICT(category_id) DO UPDATE SET limit_amount=excluded.limit_amount",
                           (cid, limit))
        self.c.commit()

    def add_op(self, d, amount, cid, comment):
        self.c.execute("INSERT INTO operations(date, amount, category_id, comment) VALUES(?,?,?,?)",
                       (d, amount, cid, comment))
        self.c.commit()

    def update_op(self, oid, d, amount, cid, comment):
        self.c.execute("UPDATE operations SET date=?, amount=?, category_id=?, comment=? WHERE id=?",
                       (d, amount, cid, comment, oid))
        self.c.commit()

    def delete_op(self, oid):
        self.c.execute("DELETE FROM operations WHERE id=?", (oid,))
        self.c.commit()

    def ops(self, d1, d2):
        return self.c.execute(
            "SELECT o.id, o.date, c.name, o.amount, o.comment, o.category_id "
            "FROM operations o JOIN categories c ON c.id=o.category_id "
            "WHERE o.date BETWEEN ? AND ? ORDER BY o.date DESC, o.id DESC", (d1, d2)).fetchall()

    def report(self, d1, d2):
        """(id, категория, потрачено, лимит) по всем категориям за период."""
        return self.c.execute(
            "SELECT c.id, c.name, COALESCE(SUM(o.amount), 0) AS spent, COALESCE(b.limit_amount, 0) "
            "FROM categories c "
            "LEFT JOIN operations o ON o.category_id=c.id AND o.date BETWEEN ? AND ? "
            "LEFT JOIN budgets b ON b.category_id=c.id "
            "GROUP BY c.id ORDER BY spent DESC, c.name", (d1, d2)).fetchall()

    def limits(self):
        return dict(self.c.execute("SELECT category_id, limit_amount FROM budgets").fetchall())


# ------------------------------------------------------------ валидация ----
def parse_date(s):
    return datetime.strptime(s.strip(), "%Y-%m-%d").date().isoformat()


def parse_amount(s):
    v = float(s.strip().replace(",", ".").replace(" ", ""))
    if v <= 0:
        raise ValueError
    return round(v, 2)


def money(v):
    return f"{v:,.2f}".replace(",", " ")


# ------------------------------------------------------- окно операции ----
class OpDialog(tk.Toplevel):
    def __init__(self, parent, cats, op=None):
        super().__init__(parent)
        self.title("Операция")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        self.cats = {name: cid for cid, name in cats}

        self.v_date = tk.StringVar(value=op[1] if op else date.today().isoformat())
        self.v_amount = tk.StringVar(value=f"{op[3]:.2f}" if op else "")
        self.v_cat = tk.StringVar(value=op[2] if op else (cats[0][1] if cats else ""))
        self.v_comment = tk.StringVar(value=op[4] if op else "")

        f = ttk.Frame(self, padding=14)
        f.pack()
        rows = [("Дата (ГГГГ-ММ-ДД)", ttk.Entry(f, textvariable=self.v_date, width=28)),
                ("Сумма", ttk.Entry(f, textvariable=self.v_amount, width=28)),
                ("Категория", ttk.Combobox(f, textvariable=self.v_cat, values=list(self.cats),
                                           state="readonly", width=25)),
                ("Комментарий", ttk.Entry(f, textvariable=self.v_comment, width=28))]
        for i, (label, widget) in enumerate(rows):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=4)
            widget.grid(row=i, column=1, pady=4, padx=(10, 0))
        rows[1][1].focus()
        b = ttk.Frame(f)
        b.grid(row=4, column=0, columnspan=2, pady=(10, 0), sticky="e")
        ttk.Button(b, text="Сохранить", command=self.save).pack(side="left", padx=4)
        ttk.Button(b, text="Отмена", command=self.destroy).pack(side="left")
        self.bind("<Return>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_window()

    def save(self):
        try:
            d = parse_date(self.v_date.get())
        except ValueError:
            return messagebox.showerror("Ошибка", "Дата должна быть в формате ГГГГ-ММ-ДД.", parent=self)
        try:
            a = parse_amount(self.v_amount.get())
        except ValueError:
            return messagebox.showerror("Ошибка", "Сумма должна быть числом больше нуля.", parent=self)
        if self.v_cat.get() not in self.cats:
            return messagebox.showerror("Ошибка", "Выберите категорию.", parent=self)
        self.result = (d, a, self.cats[self.v_cat.get()], self.v_comment.get().strip())
        self.destroy()


# ------------------------------------------------------------ приложение ----
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Дневник личных расходов")
        self.geometry("1100x680")
        self.minsize(900, 560)
        self.db = Db()
        today = date.today()
        self.v_from = tk.StringVar(value=today.replace(day=1).isoformat())
        self.v_to = tk.StringVar(value=today.replace(day=monthrange(today.year, today.month)[1]).isoformat())
        self.v_total = tk.StringVar()
        self.build()
        self.refresh()

    # --- интерфейс
    def build(self):
        bar = ttk.Frame(self, padding=(12, 10))
        bar.pack(fill="x")
        ttk.Label(bar, text="Период с").pack(side="left")
        ttk.Entry(bar, textvariable=self.v_from, width=12).pack(side="left", padx=4)
        ttk.Label(bar, text="по").pack(side="left")
        ttk.Entry(bar, textvariable=self.v_to, width=12).pack(side="left", padx=4)
        ttk.Button(bar, text="Применить", command=self.refresh).pack(side="left", padx=4)
        ttk.Button(bar, text="Этот месяц", command=self.this_month).pack(side="left")
        ttk.Label(bar, textvariable=self.v_total, font=("", 12, "bold")).pack(side="right")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.tab_ops, self.tab_cats, self.tab_rep = ttk.Frame(nb), ttk.Frame(nb), ttk.Frame(nb)
        nb.add(self.tab_ops, text="Операции")
        nb.add(self.tab_cats, text="Категории и бюджет")
        nb.add(self.tab_rep, text="Отчёт")
        self.build_ops()
        self.build_cats()
        self.build_report()

    def build_ops(self):
        btns = ttk.Frame(self.tab_ops, padding=8)
        btns.pack(fill="x")
        for text, cmd in [("Добавить", self.add_op), ("Изменить", self.edit_op),
                          ("Удалить", self.del_op), ("Экспорт в CSV", self.export_csv)]:
            ttk.Button(btns, text=text, command=cmd).pack(side="left", padx=(0, 6))
        cols = ("date", "cat", "amount", "comment")
        self.t_ops = ttk.Treeview(self.tab_ops, columns=cols, show="headings", selectmode="browse")
        for c, h, w, a in [("date", "Дата", 110, "w"), ("cat", "Категория", 180, "w"),
                           ("amount", "Сумма", 120, "e"), ("comment", "Комментарий", 400, "w")]:
            self.t_ops.heading(c, text=h)
            self.t_ops.column(c, width=w, anchor=a)
        self.t_ops.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.t_ops.bind("<Double-1>", lambda e: self.edit_op())
        self.empty_lbl = ttk.Label(self.tab_ops, text="За выбранный период операций нет.\nНажмите «Добавить».",
                                   justify="center", foreground="#888")

    def build_cats(self):
        top = ttk.Frame(self.tab_cats, padding=8)
        top.pack(fill="x")
        self.v_newcat = tk.StringVar()
        ttk.Entry(top, textvariable=self.v_newcat, width=24).pack(side="left")
        ttk.Button(top, text="Добавить категорию", command=self.add_cat).pack(side="left", padx=6)
        ttk.Button(top, text="Задать лимит", command=self.set_limit).pack(side="left", padx=6)
        ttk.Button(top, text="Удалить категорию", command=self.del_cat).pack(side="left")
        self.t_cats = ttk.Treeview(self.tab_cats, columns=("name", "limit"), show="headings",
                                   selectmode="browse")
        self.t_cats.heading("name", text="Категория")
        self.t_cats.heading("limit", text="Лимит на период")
        self.t_cats.column("name", width=280)
        self.t_cats.column("limit", width=160, anchor="e")
        self.t_cats.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        ttk.Label(self.tab_cats, text="Лимит 0 или пустой — бюджет для категории не задан.",
                  foreground="#666").pack(anchor="w", padx=8, pady=(0, 8))

    def build_report(self):
        self.canvas = tk.Canvas(self.tab_rep, width=430, bg="white", highlightthickness=0)
        self.canvas.pack(side="left", fill="y", padx=8, pady=8)
        right = ttk.Frame(self.tab_rep)
        right.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=8)
        cols = ("cat", "spent", "limit", "pct", "status")
        self.t_rep = ttk.Treeview(right, columns=cols, show="headings", selectmode="none")
        for c, h, w, a in [("cat", "Категория", 140, "w"), ("spent", "Потрачено", 100, "e"),
                           ("limit", "Лимит", 100, "e"), ("pct", "%", 60, "e"),
                           ("status", "Статус", 130, "w")]:
            self.t_rep.heading(c, text=h)
            self.t_rep.column(c, width=w, anchor=a)
        self.t_rep.tag_configure("warn", background="#fff3cd")
        self.t_rep.tag_configure("over", background="#f8d7da")
        self.t_rep.pack(fill="both", expand=True)
        ttk.Button(right, text="Экспорт отчёта в CSV", command=self.export_report).pack(anchor="e", pady=(8, 0))

    # --- период
    def period(self):
        try:
            d1, d2 = parse_date(self.v_from.get()), parse_date(self.v_to.get())
        except ValueError:
            messagebox.showerror("Ошибка", "Даты периода должны быть в формате ГГГГ-ММ-ДД.")
            return None
        if d1 > d2:
            messagebox.showerror("Ошибка", "Начало периода позже его конца.")
            return None
        return d1, d2

    def this_month(self):
        t = date.today()
        self.v_from.set(t.replace(day=1).isoformat())
        self.v_to.set(t.replace(day=monthrange(t.year, t.month)[1]).isoformat())
        self.refresh()

    # --- обновление данных на экране
    def refresh(self):
        p = self.period()
        if not p:
            return
        d1, d2 = p
        ops = self.db.ops(d1, d2)
        self.t_ops.delete(*self.t_ops.get_children())
        for oid, d, cat, amount, comment, _ in ops:
            self.t_ops.insert("", "end", iid=str(oid), values=(d, cat, money(amount), comment))
        if ops:
            self.empty_lbl.place_forget()
        else:
            self.empty_lbl.place(in_=self.t_ops, relx=0.5, rely=0.5, anchor="center")

        rep = self.db.report(d1, d2)
        total = sum(r[2] for r in rep)
        self.v_total.set(f"Итого за период: {money(total)}")

        limits = self.db.limits()
        self.t_cats.delete(*self.t_cats.get_children())
        for cid, name in self.db.categories():
            self.t_cats.insert("", "end", iid=str(cid), values=(name, money(limits[cid]) if cid in limits else "—"))

        self.t_rep.delete(*self.t_rep.get_children())
        for cid, name, spent, limit in rep:
            if limit > 0:
                pct = spent / limit * 100
                status, tag = ("перерасход", "over") if pct > 100 else \
                              ("близко к лимиту", "warn") if pct > 80 else ("в норме", "")
                self.t_rep.insert("", "end", values=(name, money(spent), money(limit), f"{pct:.0f}", status),
                                  tags=(tag,) if tag else ())
            else:
                self.t_rep.insert("", "end", values=(name, money(spent), "—", "—", "лимит не задан"))
        self.draw_pie(rep, total)

    def draw_pie(self, rep, total):
        cv = self.canvas
        cv.delete("all")
        data = [(n, s) for _, n, s, _ in rep if s > 0]
        if not data:
            cv.create_text(215, 150, text="Нет расходов за период", fill="#888", font=("", 12))
            return
        x0, y0, x1, y1 = 60, 20, 370, 330
        start = 90.0
        for i, (name, s) in enumerate(data):
            extent = -s / total * 360
            color = COLORS[i % len(COLORS)]
            if len(data) == 1:
                cv.create_oval(x0, y0, x1, y1, fill=color, outline="white", width=2)
            else:
                cv.create_arc(x0, y0, x1, y1, start=start, extent=extent, fill=color,
                              outline="white", width=2, style="pieslice")
            start += extent
        for i, (name, s) in enumerate(data):
            y = 350 + i * 22
            cv.create_rectangle(40, y, 54, y + 14, fill=COLORS[i % len(COLORS)], outline="")
            cv.create_text(62, y + 7, anchor="w", text=f"{name} — {money(s)} ({s / total * 100:.0f}%)")
        cv.config(scrollregion=(0, 0, 430, 350 + len(data) * 22 + 10))

    # --- операции
    def selected_op(self):
        sel = self.t_ops.selection()
        if not sel:
            messagebox.showinfo("Выбор", "Сначала выберите операцию в списке.")
            return None
        return int(sel[0])

    def add_op(self):
        cats = self.db.categories()
        if not cats:
            return messagebox.showinfo("Нет категорий", "Сначала создайте категорию.")
        dlg = OpDialog(self, cats)
        if dlg.result:
            self.db.add_op(*dlg.result)
            self.refresh()

    def edit_op(self):
        oid = self.selected_op()
        if oid is None:
            return
        p = self.period()
        op = next((o for o in self.db.ops(*p) if o[0] == oid), None) if p else None
        if not op:
            return
        dlg = OpDialog(self, self.db.categories(), op)
        if dlg.result:
            self.db.update_op(oid, *dlg.result)
            self.refresh()

    def del_op(self):
        oid = self.selected_op()
        if oid is not None and messagebox.askyesno("Удаление", "Удалить выбранную операцию?"):
            self.db.delete_op(oid)
            self.refresh()

    # --- категории и бюджет
    def selected_cat(self):
        sel = self.t_cats.selection()
        if not sel:
            messagebox.showinfo("Выбор", "Сначала выберите категорию в списке.")
            return None
        return int(sel[0])

    def add_cat(self):
        name = self.v_newcat.get().strip()
        if not name:
            return messagebox.showerror("Ошибка", "Введите название категории.")
        try:
            self.db.add_category(name)
        except sqlite3.IntegrityError:
            return messagebox.showerror("Ошибка", "Такая категория уже существует.")
        self.v_newcat.set("")
        self.refresh()

    def del_cat(self):
        cid = self.selected_cat()
        if cid is None or not messagebox.askyesno("Удаление", "Удалить выбранную категорию?"):
            return
        try:
            self.db.delete_category(cid)
        except ValueError as e:
            return messagebox.showerror("Нельзя удалить", str(e))
        self.refresh()

    def set_limit(self):
        cid = self.selected_cat()
        if cid is None:
            return
        val = simpledialog.askstring("Лимит", "Лимит на период (0 — убрать лимит):", parent=self)
        if val is None:
            return
        try:
            limit = float(val.replace(",", ".").replace(" ", ""))
            if limit < 0:
                raise ValueError
        except ValueError:
            return messagebox.showerror("Ошибка", "Введите число не меньше нуля.")
        self.db.set_limit(cid, limit)
        self.refresh()

    # --- экспорт
    def export_csv(self):
        p = self.period()
        if not p:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="operations.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["Дата", "Категория", "Сумма", "Комментарий"])
                for _, d, cat, amount, comment, _ in self.db.ops(*p):
                    w.writerow([d, cat, amount, comment])

    def export_report(self):
        p = self.period()
        if not p:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="report.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["Категория", "Потрачено", "Лимит"])
                for _, name, spent, limit in self.db.report(*p):
                    w.writerow([name, spent, limit])


if __name__ == "__main__":
    App().mainloop()

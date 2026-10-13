# -*- coding: utf-8 -*-
"""
Trung Tâm Dạy Kèm Cô Điệp - Sổ theo dõi học viên và học phí
Bản Kivy (chạy được trên Windows / macOS / Linux / Android).

Dữ liệu tự lưu vào:  Documents/QuanLyHocVien/hocvien.json   (Android: thư mục dữ liệu của ứng dụng)
Sao lưu mỗi ngày:    .../SaoLuu/

Cài đặt:   pip install kivy pillow
Chạy:      python quanly_hocvien_kivy.py
"""
import base64
import calendar
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time
import traceback
import unicodedata
from pathlib import Path
from string import Template

from kivy.app import App
from kivy.base import ExceptionHandler, ExceptionManager
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import (BooleanProperty, ListProperty, NumericProperty,
                             ObjectProperty, StringProperty)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.utils import get_color_from_hex as hexc, platform

try:
    from PIL import Image as PILImage, ImageOps
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ============================================================ hằng số
APP_TITLE = "Trung Tâm Dạy Kèm Cô Điệp"
SUBJECTS = ["Toán", "Tiếng Việt", "Văn", "KHTN", "English", "Music", "Tiếng Trung"]
CHIPS = [("#2347c8", "#e1e8ff"), ("#c2410c", "#ffe8da"), ("#be185d", "#fde2ee"),
         ("#15803d", "#dcf5e4"), ("#6d28d9", "#ece3ff"), ("#a16207", "#fff0c4"),
         ("#b91c1c", "#fee2e2")]
DAYS_LIMIT = 30
LEGACY_HASH = 8500302101123492      # mật khẩu cũ của bản HTML (giữ nguyên để không phải đổi)

NAVY, INK, MUTED, PAPER, DESK = "#1d2f6f", "#1f2a44", "#62708f", "#fffefb", "#f1f5fc"
LINE, PRIMARY, GREEN, RED, HL = "#d9e2f3", "#2f55d4", "#1f9d6b", "#e0474c", "#ffe27a"
GREENBG, REDBG, SOFT = "#e8f7ef", "#fdecec", "#e6ebf7"
AV_COLORS = ["#2f55d4", "#1f9d6b", "#e0474c", "#7c3aed", "#c2410c", "#be185d", "#0e7490"]

SORT_OPTIONS = [
    ("Thứ tự nhập", ""),
    ("Ngày nhập học: cũ đến mới", "nhaphoc:asc"), ("Ngày nhập học: mới đến cũ", "nhaphoc:desc"),
    ("Ngày tính phí: cũ đến mới", "ngaydong:asc"), ("Ngày tính phí: mới đến cũ", "ngaydong:desc"),
    ("Tên gọi: A đến Z", "ten:asc"), ("Tên gọi: Z đến A", "ten:desc"),
    ("Họ và tên: A đến Z", "hoten:asc"), ("Họ và tên: Z đến A", "hoten:desc"),
    ("Lớp: A đến Z", "lop:asc"),
]


# ============================================================ tiện ích ngày / tiền / chuỗi
def today_iso():
    return dt.date.today().isoformat()


def this_month():
    return today_iso()[:7]


def to_vn(iso):
    return "/".join(reversed(iso.split("-"))) if iso else ""


def to_iso(vn):
    p = (vn or "").strip().split("/")
    return f"{p[2]}-{p[1].zfill(2)}-{p[0].zfill(2)}" if len(p) == 3 else ""


def valid_vn(s):
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", (s or "").strip())
    if not m:
        return False
    try:
        dt.date(int(m[3]), int(m[2]), int(m[1]))
        return True
    except ValueError:
        return False


def month_to_iso(v):
    m = re.fullmatch(r"(\d{2})/(\d{4})", (v or "").strip())
    return f"{m[2]}-{m[1]}" if m else ""


def money(n):
    return f"{n:,}".replace(",", ".") + " đ" if n > 0 else ""


def parse_int(s):
    return int(re.sub(r"\D", "", str(s or "")) or 0)


def clean(s):
    return re.sub(r"[|\r\n]", " ", s or "").strip()


def days_since(iso):
    try:
        return (dt.date.today() - dt.date.fromisoformat(iso)).days
    except ValueError:
        return 0


def key(r):
    return r["ten"].strip().lower() + "|" + r["lop"].strip().lower()


def is_paid(r):
    return r["tien"] > 0 and (r.get("ngaydong") or "")[:7] == this_month()


def last_pay_map(records):
    mp = {}
    for r in records:
        if r["tien"] > 0 and r.get("ngaydong"):
            k = key(r)
            if k not in mp or r["ngaydong"] > mp[k]:
                mp[k] = r["ngaydong"]
    return mp


def is_overdue(k, mp):
    """Chưa đóng: chưa từng đóng, hoặc lần đóng cuối cách hôm nay quá DAYS_LIMIT (30) ngày."""
    last = mp.get(k)
    return (not last) or days_since(last) > DAYS_LIMIT


def status_text(r, mp):
    last = mp.get(key(r))
    if not last:
        return "Chưa đóng tiền", "bad"
    n = days_since(last)
    if n > DAYS_LIMIT:
        return f"Chưa đóng tháng mới (lần cuối {to_vn(last)}, {n} ngày trước)", "bad"
    return f"Còn trong hạn (đóng {n} ngày trước)", "ok"


# ---- sắp xếp tiếng Việt: a ă â b c d đ e ê g h i k l m n o ô ơ p q r s t u ư v x y
_LETTERS = ["a", "ă", "â", "b", "c", "d", "đ", "e", "ê", "g", "h", "i", "k", "l", "m",
            "n", "o", "ô", "ơ", "p", "q", "r", "s", "t", "u", "ư", "v", "x", "y"]
_LIDX = {unicodedata.normalize("NFD", c): i for i, c in enumerate(_LETTERS)}
_TONE = {0x300: 1, 0x309: 2, 0x303: 3, 0x301: 4, 0x323: 5}      # huyền, hỏi, ngã, sắc, nặng


def vi_key(s):
    s = unicodedata.normalize("NFD", (s or "").strip().lower())
    prim, tone = [], []
    for ch in s:
        o = ord(ch)
        if o in _TONE:
            if tone:
                tone[-1] = _TONE[o]
        elif o in (0x306, 0x302, 0x31B):            # ă â ê ô ơ ư
            if prim:
                prim[-1] += ch
        else:
            prim.append(ch)
            tone.append(0)
    p = []
    for c in prim:
        if c in _LIDX:
            p.append(_LIDX[c])
        elif c[0].isalpha():
            p.append(100 + ord(c[0]))
        else:
            p.append(ord(c[0]) - 1000)              # khoảng trắng, số đứng trước chữ
    return (p, tone)


def name_key(n):
    """'Nguyễn Văn An' -> 'An Nguyễn Văn' (xếp theo tên gọi trước)."""
    w = (n or "").strip().split()
    return (w[-1] + " " + " ".join(w[:-1])) if len(w) > 1 else (w[0] if w else "")


def sort_rows(rows, sort_key, sort_dir):
    """rows = [(index, record)]. Giữ đúng cách xếp của bản HTML."""
    if not sort_key:
        return rows
    rev = sort_dir == "desc"
    if sort_key in ("ten", "hoten"):
        f = name_key if sort_key == "ten" else (lambda n: n.strip())
        rows = sorted(rows, key=lambda x: (vi_key(x[1]["lop"]), x[1].get("nhaphoc") or ""))
        return sorted(rows, key=lambda x: vi_key(f(x[1]["ten"])), reverse=rev)
    if sort_key == "tien":
        return sorted(rows, key=lambda x: x[1]["tien"], reverse=rev)
    full = [x for x in rows if x[1].get(sort_key)]
    empty = [x for x in rows if not x[1].get(sort_key)]     # ô trống luôn xuống cuối
    if sort_key == "lop":
        full = sorted(full, key=lambda x: vi_key(x[1]["lop"]), reverse=rev)
    else:
        full = sorted(full, key=lambda x: x[1][sort_key], reverse=rev)
    return full + empty


# ============================================================ mật khẩu
def cyrb53(s, seed=0):
    M = 0xFFFFFFFF
    h1, h2 = (0xdeadbeef ^ seed) & M, (0x41c6ce57 ^ seed) & M
    for ch in s:
        c = ord(ch)
        h1 = ((h1 ^ c) * 2654435761) & M
        h2 = ((h2 ^ c) * 1597334677) & M
    h1 = ((((h1 ^ (h1 >> 16)) * 2246822507) & M) ^ (((h2 ^ (h2 >> 13)) * 3266489909) & M)) & M
    h2 = ((((h2 ^ (h2 >> 16)) * 2246822507) & M) ^ (((h1 ^ (h1 >> 13)) * 3266489909) & M)) & M
    return 4294967296 * (h2 & 2097151) + h1


def pw_make(pw):
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 150000)
    return {"pw_salt": salt.hex(), "pw_hash": h.hex()}


def pw_check(pw, cfg):
    if cfg.get("pw_salt") and cfg.get("pw_hash"):
        h = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(cfg["pw_salt"]), 150000)
        return h.hex() == cfg["pw_hash"]
    return cyrb53(pw.strip()) == LEGACY_HASH


# ============================================================ lưu trữ dữ liệu
def data_dir(base=None):
    env = os.environ.get("QLHV_DATA")
    if env:
        d = Path(env)
    elif base:                                   # Android: thư mục riêng của ứng dụng
        d = Path(base) / "QuanLyHocVien"
    else:
        home = Path(os.path.expanduser("~"))
        d = (home / "Documents" if (home / "Documents").exists() else home) / "QuanLyHocVien"
    d.mkdir(parents=True, exist_ok=True)
    return d


def norm_record(x):
    return {"nhaphoc": str(x.get("nhaphoc") or ""), "ten": str(x.get("ten") or ""),
            "lop": str(x.get("lop") or ""), "mon": str(x.get("mon") or ""),
            "tien": parse_int(x.get("tien")), "ngaydong": str(x.get("ngaydong") or "")}


def records_to_text(records, photos):
    t = "# ngay_nhap_hoc|ten|lop|mon_hoc|so_tien|ngay_tinh_phi\n"
    t += "\n".join("|".join([to_vn(r["nhaphoc"]), r["ten"], r["lop"], r["mon"], str(r["tien"]),
                             to_vn(r["ngaydong"])]) for r in records) + "\n"
    if photos:
        t += "# ---- HINH ANH HOC VIEN (khong sua phan nay): #ANH|ten|lop|du_lieu_hinh ----\n"
        for k, v in photos.items():
            t += "#ANH|" + k + "|" + v + "\n"
    return t


def records_from_text(text):
    out, photos = [], {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#ANH|"):
            p = line.split("|")
            if len(p) >= 4 and p[3].startswith("data:image"):
                photos[p[1].lower() + "|" + p[2].lower()] = p[3].strip()
            continue
        if not line or line.startswith("#"):
            continue
        p = line.split("|")
        if len(p) < 3:
            continue
        p += [""] * (6 - len(p))
        out.append(norm_record({"nhaphoc": to_iso(p[0]), "ten": p[1], "lop": p[2], "mon": p[3],
                                "tien": p[4], "ngaydong": to_iso(p[5])}))
    return out, photos


def read_old_html(path):
    """Đọc dữ liệu nằm trong file quan_ly_hoc_vien.html (bản web cũ)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    m = re.search(r'<script id="app-data" type="application/json">([\s\S]*?)</script>', text)
    if not m:
        raise ValueError("File này không phải phần mềm quản lý học viên (bản HTML cũ).")
    d = json.loads(m.group(1))
    return [norm_record(x) for x in d.get("records", [])], dict(d.get("photos") or {})


class Store:
    def __init__(self, base=None):
        self.dir = data_dir(base)
        self.path = self.dir / "hocvien.json"
        self.cfg_path = self.dir / "config.json"
        self.records, self.photos, self.first_run = [], {}, not self.path.exists()
        self.cfg = {}
        if self.cfg_path.exists():
            try:
                self.cfg = json.loads(self.cfg_path.read_text(encoding="utf-8"))
            except Exception:
                self.cfg = {}
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                bak = self.path.with_suffix(".bak")
                d = json.loads(bak.read_text(encoding="utf-8")) if bak.exists() else {}
            self.records = [norm_record(x) for x in d.get("records", [])]
            self.photos = dict(d.get("photos") or {})

    def save(self):
        payload = json.dumps({"savedAt": int(time.time() * 1000), "records": self.records,
                              "photos": self.photos}, ensure_ascii=False)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(".bak"))
        os.replace(tmp, self.path)
        # sao lưu mỗi ngày 1 bản, giữ 30 bản gần nhất
        bdir = self.dir / "SaoLuu"
        bdir.mkdir(exist_ok=True)
        today = bdir / f"hocvien_{dt.date.today():%Y%m%d}.json"
        if not today.exists():
            shutil.copy2(self.path, today)
            for old in sorted(bdir.glob("hocvien_*.json"))[:-30]:
                old.unlink(missing_ok=True)

    def save_cfg(self):
        self.cfg_path.write_text(json.dumps(self.cfg), encoding="utf-8")


# ============================================================ hình ảnh
def photo_to_dataurl(path):
    """Cắt vuông ở giữa, thu về 200x200, lưu dạng data URL (giống bản cũ)."""
    if not HAS_PIL:
        raise RuntimeError("Cần cài thư viện Pillow:  pip install pillow")
    im = ImageOps.exif_transpose(PILImage.open(path)).convert("RGB")
    side = min(im.size)
    l, t = (im.width - side) // 2, (im.height - side) // 2
    im = im.crop((l, t, l + side, t + side)).resize((200, 200), PILImage.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=75)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def dataurl_to_texture(url):
    raw = base64.b64decode(url.split(",", 1)[1])
    if HAS_PIL:                                    # đổi sang PNG cho chắc chắn đọc được mọi định dạng
        buf = io.BytesIO()
        PILImage.open(io.BytesIO(raw)).convert("RGBA").save(buf, "PNG")
        buf.seek(0)
        return CoreImage(buf, ext="png").texture
    m = re.match(r"data:image/(\w+)", url)
    ext = "jpg" if not m or m[1] == "jpeg" else m[1]
    return CoreImage(io.BytesIO(raw), ext=ext).texture


# ============================================================ hộp thoại tiện ích
def wlabel(text, **kw):
    lb = Label(text=text, halign=kw.pop("halign", "left"), valign="middle", **kw)
    lb.bind(size=lambda w, s: setattr(w, "text_size", s))
    return lb


def _popup(title, content, height=240):
    return Popup(title=title, content=content, size_hint=(.92, None), height=dp(height),
                 size_hint_max_x=dp(440), auto_dismiss=False)


def msg(title, text, height=220):
    box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
    box.add_widget(wlabel(text))
    pop = _popup(title, box, height)
    box.add_widget(Btn(text="Đóng", on_release=lambda *_: pop.dismiss()))
    pop.open()


def confirm(title, text, on_yes, yes="Có", no="Không", height=220):
    box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
    box.add_widget(wlabel(text))
    row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
    pop = _popup(title, box, height)
    row.add_widget(Btn(text=no, background_color=hexc(SOFT), color=hexc(NAVY),
                       on_release=lambda *_: pop.dismiss()))
    row.add_widget(Btn(text=yes, on_release=lambda *_: (pop.dismiss(), on_yes())))
    box.add_widget(row)
    pop.open()


def choice3(title, text, a_text, on_a, b_text, on_b, height=300):
    box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
    box.add_widget(wlabel(text))
    pop = _popup(title, box, height)
    box.add_widget(Btn(text=a_text, background_color=hexc(RED),
                       on_release=lambda *_: (pop.dismiss(), on_a())))
    box.add_widget(Btn(text=b_text, background_color=hexc(GREEN),
                       on_release=lambda *_: (pop.dismiss(), on_b())))
    box.add_widget(Btn(text="Hủy", background_color=hexc(SOFT), color=hexc(NAVY),
                       on_release=lambda *_: pop.dismiss()))
    pop.open()


def ask_text(title, prompt, on_ok, password=False):
    box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
    box.add_widget(wlabel(prompt))
    ti = TextInput(multiline=False, password=password, size_hint_y=None, height=dp(44),
                   font_size=sp(16), write_tab=False)
    box.add_widget(ti)
    pop = _popup(title, box, 250)

    def ok(*_):
        v = ti.text
        pop.dismiss()
        on_ok(v)

    ti.bind(on_text_validate=ok)
    row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
    row.add_widget(Btn(text="Hủy", background_color=hexc(SOFT), color=hexc(NAVY),
                       on_release=lambda *_: pop.dismiss()))
    row.add_widget(Btn(text="OK", on_release=ok))
    box.add_widget(row)
    pop.open()
    Clock.schedule_once(lambda dt_: setattr(ti, "focus", True), .3)


def pick_file(title, filters, on_pick):
    start = "/storage/emulated/0" if platform == "android" else os.path.expanduser("~")
    fc = FileChooserListView(path=start, filters=filters)
    box = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(6))
    box.add_widget(fc)
    pop = Popup(title=title, content=box, size_hint=(.96, .92), auto_dismiss=False)

    def ok(*_):
        if fc.selection:
            pop.dismiss()
            on_pick(fc.selection[0])

    fc.bind(on_submit=lambda *_: ok())
    row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
    row.add_widget(Btn(text="Hủy", background_color=hexc(SOFT), color=hexc(NAVY),
                       on_release=lambda *_: pop.dismiss()))
    row.add_widget(Btn(text="Chọn file", on_release=ok))
    box.add_widget(row)
    pop.open()


# ============================================================ widget riêng
class Btn(Button):
    pass


class Cap(Label):
    pass


class RowLabel(Label):
    pass


class Chip(ToggleButton):
    fgc = ListProperty([0, 0, 0, 1])
    bgc = ListProperty([1, 1, 1, 1])


class TabBtn(ToggleButton):
    col = ListProperty([0, 0, 0, 1])


class Stat(BoxLayout):
    num = StringProperty("")
    lbl = StringProperty("")
    col = ListProperty([1, 1, 1, 1])


class DateInput(TextInput):
    """Ô nhập ngày dd/mm/yyyy (hoặc mm/yyyy), tự thêm dấu /."""
    month_only = BooleanProperty(False)

    def __init__(self, **kw):
        kw.setdefault("multiline", False)
        kw.setdefault("write_tab", False)
        super().__init__(**kw)
        self.bind(text=self._fmt)

    def _fmt(self, _w, v):
        d = re.sub(r"\D", "", v)[: 6 if self.month_only else 8]
        o = d[:2]
        if len(d) > 2:
            o += "/" + d[2:4 if not self.month_only else 6]
        if not self.month_only and len(d) > 4:
            o += "/" + d[4:]
        if o != v:
            self.text = o
            Clock.schedule_once(lambda dt_: setattr(self, "cursor", (len(o), 0)))


class Avatar(FloatLayout):
    idx = NumericProperty(-1)
    name = StringProperty("")
    pkey = StringProperty("")

    def __init__(self, **kw):
        super().__init__(**kw)
        self.lbl = Label(text="", bold=True, font_size=sp(22), color=(1, 1, 1, 1))
        self.add_widget(self.lbl)
        self.bind(pos=self.redraw, size=self.redraw, name=self.redraw, pkey=self.redraw)

    def redraw(self, *_):
        app = App.get_running_app()
        tex = app.photo_texture(self.pkey) if (app and self.pkey) else None
        w = self.name.strip().split()
        ch = (w[-1][0] if w else "?").upper()
        col = AV_COLORS[(len(self.name) + ord(ch)) % len(AV_COLORS)]
        self.canvas.before.clear()
        with self.canvas.before:
            if tex:
                Color(1, 1, 1, 1)
                Ellipse(pos=self.pos, size=self.size, texture=tex)
            else:
                Color(*hexc(col))
                Ellipse(pos=self.pos, size=self.size)
        self.lbl.text = "" if tex else ch

    def on_touch_down(self, touch):
        app = App.get_running_app()
        if self.collide_point(*touch.pos) and self.pkey in app.store.photos:
            app.main.view_photo(self.idx)
            return True
        return super().on_touch_down(touch)


class Row(BoxLayout):
    idx = NumericProperty(0)
    ten = StringProperty("")
    line2 = StringProperty("")
    line3 = StringProperty("")
    status = StringProperty("")
    st_color = ListProperty([0, 0, 0, 1])
    bg = ListProperty([1, 1, 1, 1])
    pkey = StringProperty("")


# ============================================================ lịch chọn ngày
class CalendarPopup(Popup):
    def __init__(self, current_vn, on_pick, **kw):
        iso = to_iso(current_vn) if valid_vn(current_vn) else today_iso()
        self.y, self.m = int(iso[:4]), int(iso[5:7])
        self.sel = iso if valid_vn(current_vn) else ""
        self.on_pick = on_pick
        super().__init__(title="Chọn ngày", size_hint=(None, None), size=(dp(340), dp(450)),
                         auto_dismiss=False, **kw)
        self.draw()

    def move(self, dm):
        n = self.y * 12 + (self.m - 1) + dm
        self.y, self.m = n // 12, n % 12 + 1
        self.draw()

    def pick(self, d):
        self.on_pick(f"{d:02d}/{self.m:02d}/{self.y}")
        self.dismiss()

    def draw(self):
        body = BoxLayout(orientation="vertical", padding=dp(6), spacing=dp(4))
        head = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(2))
        for txt, dm in (("<<", -12), ("<", -1)):
            head.add_widget(Btn(text=txt, size_hint_x=None, width=dp(44),
                                background_color=hexc(SOFT), color=hexc(PRIMARY),
                                on_release=lambda _b, dm=dm: self.move(dm)))
        head.add_widget(Label(text=f"Tháng {self.m} / {self.y}", bold=True, color=hexc(NAVY)))
        for txt, dm in ((">", 1), (">>", 12)):
            head.add_widget(Btn(text=txt, size_hint_x=None, width=dp(44),
                                background_color=hexc(SOFT), color=hexc(PRIMARY),
                                on_release=lambda _b, dm=dm: self.move(dm)))
        body.add_widget(head)

        grid = GridLayout(cols=7, spacing=dp(2))
        for w in ("T2", "T3", "T4", "T5", "T6", "T7", "CN"):
            grid.add_widget(Label(text=w, bold=True, color=hexc(MUTED), font_size=sp(12)))
        first = dt.date(self.y, self.m, 1).weekday()
        for _ in range(first):
            grid.add_widget(Label())
        today = today_iso()
        for d in range(1, calendar.monthrange(self.y, self.m)[1] + 1):
            iso = f"{self.y}-{self.m:02d}-{d:02d}"
            col = (first + d - 1) % 7
            bg, fg = (1, 1, 1, 1), hexc(RED if col == 6 else INK)
            if iso == self.sel:
                bg, fg = hexc(PRIMARY), (1, 1, 1, 1)
            elif iso == today:
                bg = hexc("#dbe5fb")
            grid.add_widget(Btn(text=str(d), size_hint_y=1, background_color=bg, color=fg,
                                bold=False, on_release=lambda _b, d=d: self.pick(d)))
        body.add_widget(grid)

        foot = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        foot.add_widget(Btn(text="Đóng", background_color=hexc(SOFT), color=hexc(NAVY),
                            on_release=lambda *_: self.dismiss()))
        t = dt.date.today()
        foot.add_widget(Btn(text="Hôm nay", on_release=lambda *_: (
            setattr(self, "y", t.year), setattr(self, "m", t.month), self.pick(t.day))))
        body.add_widget(foot)
        self.content = body


def date_row(initial, month_only=False):
    """Ô ngày + nút Lịch. Trả về (khung, ô nhập)."""
    box = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
    di = DateInput(month_only=month_only, text=initial)
    box.add_widget(di)
    box.add_widget(Btn(text="Lịch", size_hint_x=None, width=dp(64), background_color=hexc(SOFT),
                       color=hexc(NAVY),
                       on_release=lambda *_: CalendarPopup(di.text, lambda s: setattr(di, "text", s)).open()))
    return box, di


# ============================================================ form thêm / sửa học viên
class FormPopup(Popup):
    def __init__(self, main, index=None, **kw):
        self.main, self.index = main, index
        s = main.store
        r = s.records[index] if index is not None else None
        super().__init__(title="Sửa / cập nhật học viên" if r else "Thêm học viên",
                         size_hint=(.96, .96), size_hint_max_x=dp(620), auto_dismiss=False, **kw)
        self.photo = s.photos.get(key(r), "") if r else ""

        root = BoxLayout(orientation="vertical", spacing=dp(6))
        sv = ScrollView(do_scroll_x=False)
        g = GridLayout(cols=1, size_hint_y=None, spacing=dp(6), padding=dp(4))
        g.bind(minimum_height=g.setter("height"))

        # --- hình
        prow = BoxLayout(size_hint_y=None, height=dp(104), spacing=dp(10))
        self.img = Image(size_hint=(None, 1), width=dp(100))
        self.no_img = Label(text="Chưa có hình", color=hexc(MUTED), size_hint=(None, 1), width=dp(100))
        self.pbox = FloatLayout(size_hint=(None, 1), width=dp(100))
        self.pbox.add_widget(self.img)
        self.pbox.add_widget(self.no_img)
        prow.add_widget(self.pbox)
        pb = BoxLayout(orientation="vertical", spacing=dp(6))
        pb.add_widget(Btn(text="Tải hình lên", on_release=lambda *_: self.pick_photo()))
        pb.add_widget(Btn(text="Xóa hình", background_color=hexc(SOFT), color=hexc(NAVY),
                          on_release=lambda *_: self.set_photo("")))
        prow.add_widget(pb)
        g.add_widget(prow)

        # --- các ô nhập
        nh_box, self.f_nhaphoc = date_row(to_vn(r["nhaphoc"]) if r else to_vn(today_iso()))
        self.v_ten = self._ti(r["ten"] if r else "")
        self.v_lop = self._ti(r["lop"] if r else "")
        self.v_tien = self._ti(str(r["tien"] or "") if r else "", filt="int")
        nd_box, self.f_ngaydong = date_row(to_vn((r["ngaydong"] if r else "") or today_iso()))
        for lbl, w in (("Ngày nhập học", nh_box), ("Tên học viên", self.v_ten), ("Lớp", self.v_lop),
                       ("Số tiền (VNĐ)", self.v_tien), ("Ngày tính phí", nd_box)):
            g.add_widget(Cap(text=lbl))
            g.add_widget(w)

        # --- môn học
        g.add_widget(Cap(text="Môn học (chọn ít nhất 1)"))
        chosen = [x.strip() for x in r["mon"].split(",")] if r else []
        cg = GridLayout(cols=3, size_hint_y=None, spacing=dp(6), row_default_height=dp(42),
                        row_force_default=True)
        cg.bind(minimum_height=cg.setter("height"))
        self.chips = []
        for i, m in enumerate(SUBJECTS):
            fg, bg = CHIPS[i]
            c = Chip(text=m, fgc=hexc(fg), bgc=hexc(bg), state="down" if m in chosen else "normal")
            self.chips.append(c)
            cg.add_widget(c)
        g.add_widget(cg)

        sv.add_widget(g)
        root.add_widget(sv)
        foot = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        foot.add_widget(Btn(text="Hủy", background_color=hexc(SOFT), color=hexc(NAVY),
                            on_release=lambda *_: self.dismiss()))
        foot.add_widget(Btn(text="Cập nhật học viên" if r else "Lưu học viên",
                            on_release=lambda *_: self.submit()))
        root.add_widget(foot)
        self.content = root
        self.set_photo(self.photo)

    @staticmethod
    def _ti(text, filt=None):
        return TextInput(text=text, multiline=False, size_hint_y=None, height=dp(42),
                         font_size=sp(15), write_tab=False, input_filter=filt)

    # ---- hình
    def set_photo(self, data):
        self.photo = data or ""
        if self.photo:
            try:
                self.img.texture = dataurl_to_texture(self.photo)
                self.img.opacity, self.no_img.opacity = 1, 0
                return
            except Exception:
                self.photo = ""
        self.img.texture = None
        self.img.opacity, self.no_img.opacity = 0, 1

    def pick_photo(self):
        def got(path):
            try:
                self.set_photo(photo_to_dataurl(path))
            except Exception as e:
                msg("Lỗi hình", f"Không đọc được hình này.\n{e}")
        flt = ["*.jpg", "*.jpeg", "*.png", "*.bmp", "*.gif", "*.webp",
               "*.JPG", "*.JPEG", "*.PNG", "*.BMP", "*.GIF", "*.WEBP"]
        pick_file("Chọn hình học viên", flt, got)

    # ---- lưu
    def submit(self):
        s = self.main.store
        nh, ten, lop = self.f_nhaphoc.text.strip(), clean(self.v_ten.text), clean(self.v_lop.text)
        mon = [m for m, c in zip(SUBJECTS, self.chips) if c.state == "down"]
        tien = parse_int(self.v_tien.text)
        nd = self.f_ngaydong.text.strip()

        def warn(t):
            msg("Thiếu thông tin", t)

        if not valid_vn(nh):
            return warn("Ngày nhập học không hợp lệ. Nhập theo dạng dd/mm/yyyy, ví dụ 05/09/2026.")
        if not ten:
            return warn("Vui lòng nhập tên học viên.")
        if not lop:
            return warn("Vui lòng nhập lớp.")
        if not mon:
            return warn("Vui lòng chọn ít nhất 1 môn học.")
        if tien > 0 and not valid_vn(nd):
            return warn("Ngày tính phí không hợp lệ. Nhập theo dạng dd/mm/yyyy.")
        rec = {"nhaphoc": to_iso(nh), "ten": ten, "lop": lop, "mon": ", ".join(mon), "tien": tien,
               "ngaydong": to_iso(nd) if tien > 0 else ""}
        new_key, old_key = key(rec), None
        if self.index is not None:
            old_key = key(s.records[self.index])
            s.records[self.index] = rec
        else:
            s.records.append(rec)
        if self.photo:
            s.photos[new_key] = self.photo
        elif self.index is not None:
            s.photos.pop(new_key, None)
        if old_key and old_key != new_key and not any(key(x) == old_key for x in s.records):
            s.photos.pop(old_key, None)
        self.dismiss()
        self.main.commit()


# ============================================================ màn hình
class LockScreen(Screen):
    def try_unlock(self):
        app = App.get_running_app()
        if pw_check(self.ids.pw.text, app.store.cfg):
            self.ids.pw.text = ""
            self.ids.err.text = ""
            app.unlock()
        else:
            self.ids.err.text = "Sai mật khẩu, vui lòng nhập lại."
            self.ids.pw.text = ""
            self.ids.pw.focus = True


class MainScreen(Screen):
    store = ObjectProperty(None)
    info = StringProperty("")
    status = StringProperty("")
    st_all = StringProperty("0")
    st_paid = StringProperty("0")
    st_unpaid = StringProperty("0")
    st_paid_lbl = StringProperty("")
    sort_labels = ListProperty([o[0] for o in SORT_OPTIONS])

    def __init__(self, **kw):
        self.mode = "all"
        self.sort_key, self.sort_dir = "ten", "asc"
        super().__init__(**kw)
        self.status = "Dữ liệu tự động lưu trong: " + str(self.store.dir)

    # ---------- lưu ----------
    def commit(self, text=None):
        try:
            self.store.save()
            self.status = text or f"Đã tự động lưu lúc {time.strftime('%H:%M:%S')}"
        except Exception as e:
            self.status = "Không lưu được: " + str(e)
            msg("Không lưu được", str(e))
        self.render()

    # ---------- chọn dòng / thao tác ----------
    def add(self):
        FormPopup(self, None).open()

    def edit(self, idx):
        FormPopup(self, idx).open()

    def pay(self, idx):
        r = self.store.records[idx]

        def ok(v):
            tien = parse_int(v)
            if tien <= 0:
                return msg("Số tiền", "Số tiền phải lớn hơn 0.")
            if r["tien"] == 0:
                r["tien"], r["ngaydong"] = tien, today_iso()
            else:
                self.store.records.append({**r, "tien": tien, "ngaydong": today_iso()})
            self.commit()

        ask_text("Đóng tiền", f"Số tiền {r['ten']} đóng hôm nay (VNĐ):", ok)

    def delete(self, idx):
        r = self.store.records[idx]

        def do():
            k = key(r)
            del self.store.records[idx]
            if not any(key(x) == k for x in self.store.records):
                self.store.photos.pop(k, None)
            self.commit()

        confirm("Xóa", f"Xóa dòng của {r['ten']} (lớp {r['lop']})?", do, yes="Xóa")

    def view_photo(self, idx):
        if idx < 0 or idx >= len(self.store.records):
            return
        r = self.store.records[idx]
        ph = self.store.photos.get(key(r))
        if not ph:
            return msg("Chưa có hình", f"{r['ten']} chưa có hình.")
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        box.add_widget(Image(texture=dataurl_to_texture(ph)))
        box.add_widget(Label(text=r["ten"], bold=True, font_size=sp(18), size_hint_y=None, height=dp(30)))
        box.add_widget(Label(text="Lớp " + r["lop"], size_hint_y=None, height=dp(24)))
        pop = Popup(title="Hình học viên", content=box, size_hint=(.85, .8), size_hint_max_x=dp(420))
        box.add_widget(Btn(text="Đóng", on_release=lambda *_: pop.dismiss()))
        pop.open()

    # ---------- hiển thị ----------
    def set_mode(self, m):
        self.mode = m
        self.render()

    def sort_changed(self, text):
        v = dict(SORT_OPTIONS).get(text, "")
        if not v:
            self.sort_key = ""
        else:
            self.sort_key, self.sort_dir = v.split(":")
        self.render()

    def update_stats(self):
        recs = self.store.records
        allk = {key(r) for r in recs}
        paid = {key(r) for r in recs if is_paid(r)}
        mp = last_pay_map(recs)
        y, m = this_month().split("-")
        self.st_all = str(len(allk))
        self.st_paid = str(len(paid))
        self.st_unpaid = str(sum(1 for k in allk if is_overdue(k, mp)))
        self.st_paid_lbl = f"Đã đóng {m}/{y}"

    def get_rows(self):
        recs = self.store.records
        y, m = this_month().split("-")
        mt = f"{m}/{y}"
        if self.mode == "all":
            rows = list(enumerate(recs))
            title = f"Tất cả bản ghi ({len(rows)})"
        elif self.mode == "paid":
            rows = [(i, r) for i, r in enumerate(recs) if is_paid(r)]
            total = sum(r["tien"] for r in recs)
            title = f"ĐÃ ĐÓNG tháng {mt}: {len(rows)} khoản - Tổng thu: {money(total) or '0 đ'}"
        else:
            mp = last_pay_map(recs)
            latest = {}
            for i, r in enumerate(recs):
                latest[key(r)] = (i, r)
            rows = [v for k, v in latest.items() if is_overdue(k, mp)]
            title = f"CHƯA ĐÓNG (quá {DAYS_LIMIT} ngày): {len(rows)} học viên"
        rows = sort_rows(rows, self.sort_key, self.sort_dir)
        fm = month_to_iso(self.ids.f_month.text)
        if fm:
            rows = [(i, r) for i, r in rows if (r.get("nhaphoc") or "")[:7] == fm]
            title += f" - nhập học {fm[5:]}/{fm[:4]}: {len(rows)} dòng"
        return rows, title

    def render(self, *_):
        if not self.store or "rv" not in self.ids or "f_month" not in self.ids:
            return
        self.update_stats()
        rows, title = self.get_rows()
        self.info = title
        mp = last_pay_map(self.store.records)
        show = self.mode != "unpaid"
        data = []
        for i, r in rows:
            txt, st = status_text(r, mp)
            if is_paid(r):
                bg = hexc(GREENBG)
            elif self.mode == "unpaid":
                bg = hexc(REDBG)
            else:
                bg = [1, 1, 1, 1]
            l3 = "Nhập học: " + to_vn(r["nhaphoc"])
            if show and r["tien"] > 0:
                l3 += f"   Số tiền: {money(r['tien'])}   Tính phí: {to_vn(r['ngaydong'])}"
            data.append({"idx": i, "ten": r["ten"], "line2": f"Lớp {r['lop']}  -  {r['mon']}",
                         "line3": l3, "status": txt,
                         "st_color": hexc(RED if st == "bad" else GREEN),
                         "bg": bg, "pkey": key(r)})
        self.ids.rv.data = data
        self.ids.rv.refresh_from_data()

    # ---------- nhập / xuất ----------
    def apply_import(self, recs, photos, source):
        s = self.store

        def done(new_recs):
            s.records = new_recs
            s.photos.update(photos)
            self.commit(f"Đã nhập {len(recs)} dòng từ {source}")

        if s.records:
            choice3("Nhập dữ liệu",
                    f"Đã đọc {len(recs)} dòng từ {source}.\n\nThay thế toàn bộ dữ liệu hiện tại, "
                    "hay gộp thêm vào?",
                    "THAY THẾ toàn bộ", lambda: done(recs),
                    "GỘP thêm vào", lambda: done(s.records + recs))
        else:
            done(recs)

    def offer_import(self):
        confirm("Chào mừng", "Đây là lần đầu mở chương trình.\n\nBạn có muốn nhập dữ liệu từ file "
                             "HTML cũ (quan_ly_hoc_vien.html) không?", self.import_html, yes="Nhập")

    def import_html(self):
        def got(p):
            try:
                recs, photos = read_old_html(p)
            except Exception as e:
                return msg("Không đọc được", str(e))
            self.apply_import(recs, photos, os.path.basename(p))
        pick_file("Chọn file quan_ly_hoc_vien.html cũ", ["*.html", "*.htm"], got)

    def open_txt(self):
        def got(p):
            recs, photos = records_from_text(Path(p).read_text(encoding="utf-8-sig", errors="replace"))
            self.apply_import(recs, photos, os.path.basename(p))
        pick_file("Mở file .txt", ["*.txt"], got)

    def save_txt(self):
        p = self.store.dir / f"hocvien_{dt.date.today():%Y%m%d}.txt"
        p.write_text(records_to_text(self.store.records, self.store.photos), encoding="utf-8-sig")
        self.status = "Đã lưu file " + str(p)
        msg("Đã lưu", f"Đã xuất ra file:\n{p}")

    def open_folder(self):
        try:
            if sys.platform.startswith("win"):
                os.startfile(self.store.dir)
            else:
                msg("Thư mục dữ liệu", str(self.store.dir))
        except Exception as e:
            msg("Lỗi", str(e))

    def change_pw(self):
        def step1(old):
            if not pw_check(old, self.store.cfg):
                return msg("Sai mật khẩu", "Mật khẩu hiện tại không đúng.")

            def step2(n1):
                if not n1:
                    return

                def step3(n2):
                    if n1 != n2:
                        return msg("Không khớp", "Hai lần nhập không giống nhau.")
                    self.store.cfg.update(pw_make(n1))
                    self.store.save_cfg()
                    msg("Xong", "Đã đổi mật khẩu.")

                ask_text("Đổi mật khẩu", "Nhập lại mật khẩu mới:", step3, password=True)

            ask_text("Đổi mật khẩu", "Nhập mật khẩu mới:", step2, password=True)

        ask_text("Đổi mật khẩu", "Nhập mật khẩu hiện tại:", step1, password=True)

    def menu(self):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        pop = _popup("Tệp", box, 400)
        items = [("Nhập dữ liệu từ file HTML cũ", self.import_html),
                 ("Mở file .txt", self.open_txt),
                 ("Lưu ra file .txt (Notepad)", self.save_txt),
                 ("Thư mục dữ liệu / sao lưu", self.open_folder),
                 ("Đổi mật khẩu", self.change_pw)]
        for t, f in items:
            box.add_widget(Btn(text=t, on_release=lambda _b, f=f: (pop.dismiss(), f())))
        box.add_widget(Btn(text="Thoát chương trình", background_color=hexc(RED),
                           on_release=lambda *_: App.get_running_app().stop()))
        box.add_widget(Btn(text="Đóng", background_color=hexc(SOFT), color=hexc(NAVY),
                           on_release=lambda *_: pop.dismiss()))
        pop.open()


# ============================================================ giao diện (kv)
KV = Template(r"""
#:import hexc kivy.utils.get_color_from_hex

<Btn>:
    background_normal: ''
    background_down: ''
    background_color: hexc('$PRIMARY')
    color: 1, 1, 1, 1
    bold: True
    font_size: sp(14)
    size_hint_y: None
    height: dp(40)
    opacity: .75 if self.state == 'down' else 1

<Cap>:
    text_size: self.width, None
    halign: 'left'
    valign: 'bottom'
    color: hexc('$MUTED')
    bold: True
    font_size: sp(12)
    size_hint_y: None
    height: dp(22)

<RowLabel>:
    text_size: self.size
    halign: 'left'
    valign: 'middle'
    shorten: True
    shorten_from: 'right'
    color: hexc('$INK')
    font_size: sp(13)

<Chip>:
    background_normal: ''
    background_down: ''
    background_color: self.bgc if self.state == 'down' else (1, 1, 1, 1)
    color: self.fgc if self.state == 'down' else hexc('$INK')
    bold: self.state == 'down'
    font_size: sp(14)
    canvas.after:
        Color:
            rgba: hexc('$LINE')
        Line:
            rectangle: self.x, self.y, self.width, self.height

<TabBtn>:
    group: 'tab'
    allow_no_selection: False
    background_normal: ''
    background_down: ''
    background_color: self.col if self.state == 'down' else hexc('$SOFT')
    color: (1, 1, 1, 1) if self.state == 'down' else hexc('$NAVY')
    bold: True
    font_size: sp(13)

<DateInput>:
    size_hint_y: None
    height: dp(42)
    font_size: sp(15)

<Stat>:
    orientation: 'vertical'
    size_hint_x: None
    width: dp(84)
    padding: dp(6), dp(2)
    canvas.before:
        Color:
            rgba: hexc('#3a4c8a')
        Rectangle:
            pos: self.pos
            size: self.size
    Label:
        text: root.num
        color: root.col
        bold: True
        font_size: sp(20)
    Label:
        text: root.lbl
        color: hexc('#c9d5f3')
        font_size: sp(10)
        text_size: self.size
        halign: 'center'
        valign: 'top'
        shorten: True

<Row>:
    orientation: 'horizontal'
    padding: dp(8), dp(6)
    spacing: dp(8)
    canvas.before:
        Color:
            rgba: self.bg
        Rectangle:
            pos: self.pos
            size: self.size
        Color:
            rgba: hexc('$LINE')
        Rectangle:
            pos: self.x, self.y
            size: self.width, dp(1)
    Avatar:
        size_hint: None, None
        size: dp(56), dp(56)
        pos_hint: {'center_y': .5}
        idx: root.idx
        name: root.ten
        pkey: root.pkey
    BoxLayout:
        orientation: 'vertical'
        RowLabel:
            text: root.ten
            bold: True
            font_size: sp(16)
        RowLabel:
            text: root.line2
        RowLabel:
            text: root.line3
        RowLabel:
            text: root.status
            color: root.st_color
            bold: True
    BoxLayout:
        orientation: 'vertical'
        size_hint_x: None
        width: dp(100)
        spacing: dp(4)
        padding: 0, dp(8)
        Btn:
            text: 'Đóng tiền'
            height: dp(32)
            font_size: sp(12)
            background_color: hexc('$GREEN')
            on_release: app.main.pay(root.idx)
        BoxLayout:
            spacing: dp(4)
            size_hint_y: None
            height: dp(32)
            Btn:
                text: 'Sửa'
                height: dp(32)
                font_size: sp(12)
                on_release: app.main.edit(root.idx)
            Btn:
                text: 'Xóa'
                height: dp(32)
                font_size: sp(12)
                background_color: hexc('$RED')
                on_release: app.main.delete(root.idx)

<LockScreen>:
    canvas.before:
        Color:
            rgba: hexc('$DESK')
        Rectangle:
            pos: self.pos
            size: self.size
    AnchorLayout:
        BoxLayout:
            orientation: 'vertical'
            size_hint: None, None
            size: min(dp(340), root.width - dp(20)), dp(340)
            padding: dp(24)
            spacing: dp(10)
            canvas.before:
                Color:
                    rgba: hexc('$NAVY')
                Rectangle:
                    pos: self.pos
                    size: self.size
            Label:
                text: app.title
                bold: True
                font_size: sp(20)
                text_size: self.size
                halign: 'center'
                valign: 'middle'
            Label:
                text: 'Nhập mật khẩu để mở sổ theo dõi'
                color: hexc('#b9c8ee')
                font_size: sp(13)
                size_hint_y: None
                height: dp(24)
            TextInput:
                id: pw
                password: True
                multiline: False
                halign: 'center'
                font_size: sp(20)
                size_hint_y: None
                height: dp(50)
                write_tab: False
                on_text_validate: root.try_unlock()
            Btn:
                text: 'Mở trang'
                background_color: hexc('$HL')
                color: hexc('$NAVY')
                on_release: root.try_unlock()
            Label:
                id: err
                text: ''
                color: hexc('#ffb3b5')
                bold: True
                font_size: sp(13)
                size_hint_y: None
                height: dp(24)

<MainScreen>:
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        canvas.before:
            Color:
                rgba: hexc('$DESK')
            Rectangle:
                pos: self.pos
                size: self.size
        BoxLayout:
            size_hint_y: None
            height: dp(84)
            padding: dp(10)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: hexc('$NAVY')
                Rectangle:
                    pos: self.pos
                    size: self.size
            BoxLayout:
                orientation: 'vertical'
                Label:
                    text: app.title
                    bold: True
                    font_size: sp(18)
                    text_size: self.size
                    halign: 'left'
                    valign: 'middle'
                    shorten: True
                Label:
                    text: 'Sổ theo dõi học viên và học phí'
                    color: hexc('#b9c8ee')
                    font_size: sp(12)
                    text_size: self.size
                    halign: 'left'
                    valign: 'top'
                    shorten: True
            Stat:
                num: root.st_all
                lbl: 'Học viên'
            Stat:
                num: root.st_paid
                lbl: root.st_paid_lbl
                col: hexc('#8ff0c4')
            Stat:
                num: root.st_unpaid
                lbl: 'Quá hạn 30 ngày'
                col: hexc('#ffb3b5')
        BoxLayout:
            size_hint_y: None
            height: dp(40)
            spacing: dp(4)
            TabBtn:
                text: 'Đã đóng'
                col: hexc('$GREEN')
                on_release: root.set_mode('paid')
            TabBtn:
                text: 'Chưa đóng'
                col: hexc('$RED')
                on_release: root.set_mode('unpaid')
            TabBtn:
                text: 'Tất cả'
                col: hexc('$NAVY')
                state: 'down'
                on_release: root.set_mode('all')
        BoxLayout:
            size_hint_y: None
            height: dp(42)
            spacing: dp(6)
            DateInput:
                id: f_month
                month_only: True
                hint_text: 'Lọc tháng nhập học mm/yyyy'
                size_hint_x: .42
                on_text: root.render()
            Spinner:
                id: sort_sp
                text: 'Tên gọi: A đến Z'
                values: root.sort_labels
                font_size: sp(13)
                on_text: root.sort_changed(self.text)
        BoxLayout:
            size_hint_y: None
            height: dp(40)
            spacing: dp(6)
            Btn:
                text: 'Thêm học viên'
                on_release: root.add()
            Btn:
                text: 'Menu'
                size_hint_x: .3
                background_color: hexc('$SOFT')
                color: hexc('$NAVY')
                on_release: root.menu()
        Label:
            text: root.info
            bold: True
            color: hexc('$NAVY')
            font_size: sp(14)
            size_hint_y: None
            height: dp(26)
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            shorten: True
        RecycleView:
            id: rv
            viewclass: 'Row'
            bar_width: dp(6)
            scroll_type: ['bars', 'content']
            canvas.before:
                Color:
                    rgba: 1, 1, 1, 1
                Rectangle:
                    pos: self.pos
                    size: self.size
            RecycleBoxLayout:
                default_size: None, dp(112)
                default_size_hint: 1, None
                size_hint_y: None
                height: self.minimum_height
                orientation: 'vertical'
        Label:
            text: root.status
            color: hexc('$MUTED')
            font_size: sp(11)
            size_hint_y: None
            height: dp(20)
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            shorten: True
""").substitute(PRIMARY=PRIMARY, MUTED=MUTED, INK=INK, LINE=LINE, SOFT=SOFT, NAVY=NAVY,
                GREEN=GREEN, RED=RED, HL=HL, DESK=DESK)

Builder.load_string(KV)


# ============================================================ ứng dụng
class LogHandler(ExceptionHandler):
    """Ghi lỗi vào loi.log nhưng không làm chương trình tắt."""

    def handle_exception(self, inst):
        try:
            app = App.get_running_app()
            d = app.store.dir if app and getattr(app, "store", None) else Path(".")
            (d / "loi.log").write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        return ExceptionManager.PASS


class QuanLyApp(App):
    title = APP_TITLE

    def build(self):
        Window.clearcolor = hexc(DESK)
        if platform in ("win", "linux", "macosx"):
            Window.size = (1100, 760)
        self.store = Store(self.user_data_dir if platform == "android" else None)
        self.tex_cache = {}
        self.sm = ScreenManager(transition=NoTransition())
        self.main = MainScreen(name="main", store=self.store)
        self.sm.add_widget(LockScreen(name="lock"))
        self.sm.add_widget(self.main)
        self.sm.current = "lock"
        return self.sm

    def unlock(self):
        self.sm.current = "main"
        self.main.render()
        if self.store.first_run and not self.store.records:
            Clock.schedule_once(lambda dt_: self.main.offer_import(), .4)

    def photo_texture(self, pkey):
        ph = self.store.photos.get(pkey)
        if not ph:
            return None
        h = hash(ph)
        c = self.tex_cache.get(pkey)
        if c and c[0] == h:
            return c[1]
        try:
            tex = dataurl_to_texture(ph)
        except Exception:
            return None
        self.tex_cache[pkey] = (h, tex)
        return tex


if __name__ == "__main__":
    ExceptionManager.add_handler(LogHandler())
    QuanLyApp().run()

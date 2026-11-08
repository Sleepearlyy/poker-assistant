"""Always-on-top, click-to-capture poker assistant. No periodic screen capture.

The window hides only for the moment of the screenshot, then shows the OCR
result plus the local solver's action frequencies and chip EVs.
"""
import argparse
import ctypes
import json
import os
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import traceback

import mss
import numpy as np
from reader import DATA, ROOT, Reader, enable_dpi, load_image, load_layout, select_region, trim_titlebar, write_json
from advisor import analyze
from core import format_chips
from app_info import VERSION

SETTINGS=DATA/'popup-settings.json'
ACTIONS={'fold':'弃牌','check':'过牌','call':'跟注','bet':'下注','raise':'加注','all_in':'全下',
         'small_blind':'小盲','big_blind':'大盲'}

def price_text(result):
    """Call, check, or all-in. A short stack often has no separate call button."""
    controls=result.get('controls') or {}
    source=controls.get('source')
    amount=controls.get('to_call')
    if source=='check_button':return '过牌'
    if source in ('all_in_button','all_in_for_stack'):
        return '全下' if amount is None else f'全下 {amount}'
    return '跟注 未知' if amount is None else f'跟注 {amount}'

def seat_label(seat):
    """Button-relative seat name. Hero is always marked; empty chairs stay empty."""
    if seat.get('seat') == 'bottom':
        if seat.get('presence') != 'occupied':
            return '自己'
        return (seat.get('role') or '在局') + ' · 自己'
    if seat.get('presence') != 'occupied':
        return '空位'
    return seat.get('role') or '在局'
GA_ROOT=2
SW_RESTORE=9

user=ctypes.windll.user32
gdi32=ctypes.windll.gdi32
user.FindWindowW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR];user.FindWindowW.restype=wintypes.HWND
user.GetForegroundWindow.restype=wintypes.HWND
user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];user.GetAncestor.restype=wintypes.HWND
user.IsWindowVisible.argtypes=[wintypes.HWND];user.IsWindowVisible.restype=wintypes.BOOL
user.IsIconic.argtypes=[wintypes.HWND];user.IsIconic.restype=wintypes.BOOL
user.GetWindowTextLengthW.argtypes=[wintypes.HWND];user.GetWindowTextLengthW.restype=ctypes.c_int
user.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int];user.GetWindowTextW.restype=ctypes.c_int
user.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
user.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
user.SetForegroundWindow.argtypes=[wintypes.HWND]
user.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
user.SetWindowPos.restype=wintypes.BOOL
user.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
user.GetAsyncKeyState.argtypes=[ctypes.c_int];user.GetAsyncKeyState.restype=ctypes.c_short
user.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int];user.GetClassNameW.restype=ctypes.c_int
user.GetDC.argtypes=[wintypes.HWND];user.GetDC.restype=wintypes.HDC
user.ReleaseDC.argtypes=[wintypes.HWND,wintypes.HDC];user.ReleaseDC.restype=ctypes.c_int
user.PrintWindow.argtypes=[wintypes.HWND,wintypes.HDC,wintypes.UINT];user.PrintWindow.restype=wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes=[wintypes.HDC];gdi32.CreateCompatibleDC.restype=wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes=[wintypes.HDC,ctypes.c_int,ctypes.c_int];gdi32.CreateCompatibleBitmap.restype=wintypes.HBITMAP
gdi32.SelectObject.argtypes=[wintypes.HDC,wintypes.HGDIOBJ];gdi32.SelectObject.restype=wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes=[wintypes.HGDIOBJ];gdi32.DeleteObject.restype=wintypes.BOOL
gdi32.DeleteDC.argtypes=[wintypes.HDC];gdi32.DeleteDC.restype=wintypes.BOOL
gdi32.GetDIBits.argtypes=[wintypes.HDC,wintypes.HBITMAP,wintypes.UINT,wintypes.UINT,ctypes.c_void_p,ctypes.c_void_p,wintypes.UINT]
gdi32.GetDIBits.restype=ctypes.c_int

WH_KEYBOARD_LL=13
WM_KEYDOWN,WM_KEYUP,WM_SYSKEYDOWN,WM_SYSKEYUP=0x0100,0x0101,0x0104,0x0105
LLKHF_UP=0x80
VK_A,VK_Q=0x41,0x51
_MODIFIERS=(0x10,0x11,0x12,0x5B,0x5C)  # shift, ctrl, alt, left win, right win
_TEXT_CLASSES=('Edit','RichEdit','RichEdit20W','RichEdit20A','RichEdit50W')

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_=[('vkCode',wintypes.DWORD),('scanCode',wintypes.DWORD),('flags',wintypes.DWORD),
              ('time',wintypes.DWORD),('dwExtraInfo',ctypes.c_void_p)]
class GUITHREADINFO(ctypes.Structure):
    _fields_=[('cbSize',wintypes.DWORD),('flags',wintypes.DWORD),('hwndActive',wintypes.HWND),
              ('hwndFocus',wintypes.HWND),('hwndCapture',wintypes.HWND),('hwndMenuOwner',wintypes.HWND),
              ('hwndMoveSize',wintypes.HWND),('hwndCaret',wintypes.HWND),('rcCaret',wintypes.RECT)]
user.GetGUIThreadInfo.argtypes=[wintypes.DWORD,ctypes.POINTER(GUITHREADINFO)];user.GetGUIThreadInfo.restype=wintypes.BOOL
user.SetWindowsHookExW.argtypes=[ctypes.c_int,ctypes.c_void_p,wintypes.HINSTANCE,wintypes.DWORD]
user.SetWindowsHookExW.restype=wintypes.HHOOK
user.CallNextHookEx.argtypes=[wintypes.HHOOK,ctypes.c_int,wintypes.WPARAM,wintypes.LPARAM]
user.CallNextHookEx.restype=ctypes.c_ssize_t
user.UnhookWindowsHookEx.argtypes=[wintypes.HHOOK];user.UnhookWindowsHookEx.restype=wintypes.BOOL
user.GetMessageW.argtypes=[ctypes.POINTER(wintypes.MSG),wintypes.HWND,wintypes.UINT,wintypes.UINT]
user.GetMessageW.restype=ctypes.c_int
user.TranslateMessage.argtypes=[ctypes.POINTER(wintypes.MSG)];user.TranslateMessage.restype=wintypes.BOOL
user.DispatchMessageW.argtypes=[ctypes.POINTER(wintypes.MSG)];user.DispatchMessageW.restype=ctypes.c_ssize_t
user.PostThreadMessageW.argtypes=[wintypes.DWORD,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
user.PostThreadMessageW.restype=wintypes.BOOL
kernel32=ctypes.windll.kernel32
kernel32.GetCurrentThreadId.restype=wintypes.DWORD
WM_QUIT=0x0012
_HOOKPROC=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,ctypes.c_int,wintypes.WPARAM,wintypes.LPARAM)

def hotkey_action(vk,*,modifiers,typing,game_focused,panel_open):
    """Bare A scans and bare Q collapses, only while the table or this window is in front."""
    if modifiers or typing or not game_focused:return None
    if vk==VK_A:return 'scan'
    if vk==VK_Q and panel_open:return 'collapse'
    return None

def _modifiers_down():
    return any(user.GetAsyncKeyState(vk)&0x8000 for vk in _MODIFIERS)

def _typing():
    """An edit box has the caret. A plain window caret (the assistant, most games) does not."""
    info=GUITHREADINFO();info.cbSize=ctypes.sizeof(GUITHREADINFO)
    if not user.GetGUIThreadInfo(0,ctypes.byref(info)) or not info.hwndFocus:return False
    name=ctypes.create_unicode_buffer(64)
    user.GetClassNameW(info.hwndFocus,name,64)
    return name.value in _TEXT_CLASSES or name.value.startswith('RichEdit')

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_=[('biSize',wintypes.DWORD),('biWidth',ctypes.c_long),('biHeight',ctypes.c_long),
              ('biPlanes',wintypes.WORD),('biBitCount',wintypes.WORD),('biCompression',wintypes.DWORD),
              ('biSizeImage',wintypes.DWORD),('biXPelsPerMeter',ctypes.c_long),('biYPelsPerMeter',ctypes.c_long),
              ('biClrUsed',wintypes.DWORD),('biClrImportant',wintypes.DWORD)]
class BITMAPINFO(ctypes.Structure):
    _fields_=[('bmiHeader',BITMAPINFOHEADER),('bmiColors',wintypes.DWORD*3)]

def grab_window(hwnd):
    """Render a window's client area with PrintWindow, so it works while covered.

    Returns a BGR numpy array, or None when the window cannot be rendered (e.g.
    minimized, or a driver that ignores PW_RENDERFULLCONTENT).
    """
    if not hwnd or user.IsIconic(hwnd):return None
    rect=wintypes.RECT()
    if not user.GetClientRect(hwnd,ctypes.byref(rect)):return None
    w,h=rect.right,rect.bottom
    if w<300 or h<200:return None
    hdc=user.GetDC(hwnd)
    if not hdc:return None
    mem=0;bmp=0
    try:
        mem=gdi32.CreateCompatibleDC(hdc);bmp=gdi32.CreateCompatibleBitmap(hdc,w,h)
        if not mem or not bmp:return None
        gdi32.SelectObject(mem,bmp)
        if not user.PrintWindow(hwnd,mem,3):return None  # PW_CLIENTONLY|PW_RENDERFULLCONTENT
        info=BITMAPINFO();header=info.bmiHeader
        header.biSize=ctypes.sizeof(BITMAPINFOHEADER);header.biWidth=w;header.biHeight=-h
        header.biPlanes=1;header.biBitCount=32;header.biCompression=0
        buffer=ctypes.create_string_buffer(w*h*4)
        if gdi32.GetDIBits(mem,bmp,0,h,buffer,ctypes.byref(info),0)!=h:return None
        frame=np.frombuffer(buffer,dtype=np.uint8).reshape(h,w,4)[:,:,:3].copy()
        if float(frame.mean())<8 or float(frame.std())<8:return None
        return frame
    finally:
        if bmp:gdi32.DeleteObject(bmp)
        if mem:gdi32.DeleteDC(mem)
        user.ReleaseDC(hwnd,hdc)

def describe(hwnd):
    """Client-area rectangle of a visible, non-minimized, non-empty window."""
    if not hwnd or not user.IsWindowVisible(hwnd) or user.IsIconic(hwnd):return None
    length=user.GetWindowTextLengthW(hwnd)
    if length<=0:return None
    buffer=ctypes.create_unicode_buffer(length+1)
    user.GetWindowTextW(hwnd,buffer,length+1)
    title=buffer.value.strip()
    if not title:return None
    rect=wintypes.RECT();point=wintypes.POINT(0,0)
    if not user.GetClientRect(hwnd,ctypes.byref(rect)) or not user.ClientToScreen(hwnd,ctypes.byref(point)):return None
    if rect.right<300 or rect.bottom<200:return None
    return {'hwnd':int(hwnd),'title':title,
            'region':dict(left=point.x,top=point.y,width=rect.right,height=rect.bottom)}

def game_title(title):
    return 'pokerfate' in ''.join(title.casefold().split())

def game_window():
    """The Poker Fate client, including a title that is not exactly 'Poker Fate'."""
    exact=describe(user.FindWindowW(None,'Poker Fate'))
    if exact:return exact
    found=[]
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _param):
        info=describe(hwnd)
        if info and game_title(info['title']):found.append(info)
        return True
    user.EnumWindows(callback, 0)
    if not found:return None
    found.sort(key=lambda info: info['region']['width']*info['region']['height'], reverse=True)
    return found[0]

def focus_window(hwnd):
    try:
        if user.IsIconic(hwnd):user.ShowWindow(hwnd,SW_RESTORE)
        user.SetForegroundWindow(hwnd)
    except OSError:pass

def work_area(root):
    rect=wintypes.RECT()
    if user.SystemParametersInfoW(48,0,ctypes.byref(rect),0):
        return rect.left,rect.top,rect.right,rect.bottom
    return 0,0,root.winfo_screenwidth(),root.winfo_screenheight()

class PokerPopup:
    def __init__(self,root,*,sample=None,save_settings=True):
        self.root=root;self.sample=sample;self.save_settings=save_settings
        self.events=queue.Queue();self.busy=False;self.closed=False;self.expanded=False
        self.reader=None;self.reader_layout=None;self.last_result=None
        self.mode='window';self.region=None
        self.last_foreground=game_window()
        self.own_pid=os.getpid()
        self.own_hwnd=user.GetAncestor(int(root.winfo_id()),GA_ROOT)
        if save_settings and SETTINGS.exists():
            try:
                settings=json.loads(SETTINGS.read_text(encoding='utf-8'))
                if settings.get('mode')=='region' and isinstance(settings.get('region'),dict):
                    r=settings['region']
                    if all(isinstance(r.get(k),int) for k in ('left','top','width','height')) and r['width']>10 and r['height']>10:
                        self.mode='region';self.region=r
            except (ValueError,OSError):pass
        root.title(f'德扑助手 {VERSION} · 点击识别');root.attributes('-topmost',True)
        root.configure(bg='#101820');root.resizable(False,False)
        root.protocol('WM_DELETE_WINDOW',self.close)
        style=ttk.Style(root);style.theme_use('clam')
        style.configure('TFrame',background='#101820')
        style.configure('TLabel',background='#101820',foreground='#d9e4ed',font=('Microsoft YaHei UI',10))
        style.configure('Muted.TLabel',foreground='#91a6b6',font=('Microsoft YaHei UI',9))
        style.configure('Title.TLabel',font=('Microsoft YaHei UI',10,'bold'),foreground='#fafcff')
        style.configure('Accent.TButton',font=('Microsoft YaHei UI',9,'bold'),padding=(8,2),background='#38b8a3',foreground='#082422')
        style.configure('TButton',padding=(4,1),font=('Microsoft YaHei UI',8))
        style.configure('Treeview',background='#182631',fieldbackground='#182631',foreground='#e4edf4',rowheight=18,font=('Microsoft YaHei UI',9),borderwidth=0)
        style.configure('Treeview.Heading',background='#233744',foreground='#a4becd',font=('Microsoft YaHei UI',8),padding=1)
        style.map('Treeview',background=[('selected','#245c60')])
        self.outer=ttk.Frame(root,padding=(12,10));self.outer.pack(fill='both',expand=True)
        self.chip=ttk.Frame(self.outer)
        self.chip_btn=ttk.Button(self.chip,text='A 识别',style='Accent.TButton',command=self.scan)
        self.chip_btn.pack(fill='both',expand=True)
        self.chip_menu=tk.Menu(root,tearoff=0)
        self.chip_menu.add_command(label='退出',command=self.close)
        self.chip_btn.bind('<Button-3>',lambda event:self.chip_menu.tk_popup(event.x_root,event.y_root))
        header=ttk.Frame(self.outer);self.header=header
        ttk.Label(header,text='德扑助手',style='Title.TLabel').pack(side='left')
        self.scan_btn=ttk.Button(header,text='再识别 A',style='Accent.TButton',command=self.scan);self.scan_btn.pack(side='left',padx=(8,0))
        self.select_btn=ttk.Button(header,text='框选区域',command=self.choose_region);self.select_btn.pack(side='left',padx=(6,0))
        self.locate_btn=ttk.Button(header,text='定位游戏',command=self.locate);self.locate_btn.pack(side='left',padx=(6,0))
        ttk.Button(header,text='退出',command=self.close).pack(side='right')
        self.toggle_btn=ttk.Button(header,text='收起 Q',command=self.collapse);self.toggle_btn.pack(side='right',padx=(0,6))
        ttk.Button(header,text='计算依据',command=self.show_assumptions).pack(side='right',padx=(0,6))
        self.status=tk.StringVar(value='按 A 识别，按 Q 收起。')
        self.details=ttk.Frame(self.outer)
        self.target=tk.StringVar();self.update_target()
        info=ttk.Frame(self.details);info.pack(fill='x',pady=(3,0))
        self.money=tk.StringVar(value='底池 —    盲注 —')
        ttk.Label(info,textvariable=self.money,font=('Microsoft YaHei UI',9,'bold')).pack(side='left')
        self.cards=tk.StringVar(value='手牌 —    公牌 —')
        ttk.Label(info,textvariable=self.cards,font=('Segoe UI Symbol',9)).pack(side='left',padx=(10,0))
        self.equity=tk.StringVar(value='胜率 —')
        ttk.Label(info,textvariable=self.equity,font=('Microsoft YaHei UI',11,'bold'),foreground='#57d6ba').pack(side='right')
        self.recommendation=tk.StringVar(value='识别后自动分析')
        ttk.Label(self.details,textvariable=self.recommendation,font=('Microsoft YaHei UI',12,'bold'),foreground='#57d6ba').pack(anchor='w')
        ttk.Label(self.details,textvariable=self.status,style='Muted.TLabel').pack(anchor='w')
        tables=ttk.Frame(self.details);tables.pack(fill='both',expand=True,pady=(2,0))
        self.seats=ttk.Treeview(tables,columns=('seat','stack','bet','action'),show='headings',height=6,selectmode='none')
        for col,title,width in [('seat','位置',108),('stack','后手',78),('bet','下注',72),('action','动作',72)]:
            self.seats.heading(col,text=title);self.seats.column(col,width=width,anchor='center',stretch=True)
        self.seats.pack(side='left',fill='both',expand=True,padx=(0,8))
        self.ev=ttk.Treeview(tables,columns=('action','ev','bb','freq'),show='headings',height=6,selectmode='none')
        for col,title,width in [('action','候选动作',128),('ev','EV 筹码',84),('bb','EV 大盲',62),('freq','频率',52)]:
            self.ev.heading(col,text=title);self.ev.column(col,width=width,anchor='center',stretch=True)
        self.ev.tag_configure('best',foreground='#57d6ba')
        self.ev.pack(side='left',fill='both',expand=True)
        self.collapse()
        root.deiconify();root.state('normal');root.update();self.position()
        root.lift();root.attributes('-topmost',True)
        root.bind('<Destroy>',self._on_destroy)
        self._install_hotkey()
        root.after(50,self.position);root.after(80,self.poll);root.after(250,self.track_foreground)

    def position(self):
        l,t,r,b=work_area(self.root)
        self.root.update_idletasks()
        if not self.expanded:
            width,height=max(72,self.chip.winfo_reqwidth()+4),28
        else:
            width=min(780,r-l-32)
            height=min(self.root.winfo_reqheight()+6,320)
        x,y=l+16,max(t+8,b-height-(40 if self.expanded else 16))
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        self.root.attributes('-topmost',True)
        self.root.update_idletasks()
        hwnd=user.GetAncestor(int(self.root.winfo_id()),GA_ROOT)
        user.SetWindowPos(hwnd,-1,x,y,width,height,0x0040)

    def collapse(self):
        """Only the corner button stays on screen."""
        self.expanded=False
        self.details.pack_forget();self.header.pack_forget()
        self.outer.configure(padding=(3,3))
        self.chip.pack(fill='both',expand=True)
        self.root.overrideredirect(True)
        self.root.update_idletasks()
        self.position()

    def expand(self):
        """Open the result panel from the corner button."""
        self.expanded=True
        self.chip.pack_forget()
        self.outer.configure(padding=(6,4))
        self.root.overrideredirect(False)
        self.header.pack(fill='x')
        self.details.pack(fill='both',expand=True)
        self.position()
        self.root.lift()

    def update_target(self):
        if self.sample:text='示例图片测试'
        elif self.mode=='window':
            name=(self.last_foreground or {}).get('title')
            text='自动截取 '+name if name else '正在寻找 Poker Fate 窗口'
        else:text='已框选区域（游戏移动后需重新框选）'
        self.target.set(text)

    def persist(self):
        if self.save_settings:
            write_json(SETTINGS,{'mode':self.mode,'region':self.region})

    def track_foreground(self):
        if self.closed:return
        try:
            found=game_window()
            if found:
                previous=self.last_foreground or {}
                if found['hwnd']!=previous.get('hwnd') or found['region']!=previous.get('region'):
                    self.last_foreground=found
                    if self.mode=='window':self.update_target()
            else:
                hwnd=user.GetForegroundWindow()
                if hwnd and int(hwnd)!=int(self.own_hwnd):
                    pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                    got=describe(hwnd) if pid.value!=self.own_pid else None
                    if got and (not self.last_foreground or got['hwnd']!=self.last_foreground['hwnd']):
                        self.last_foreground=got
                        if self.mode=='window':self.update_target()
        except OSError:pass
        self.root.after(400,self.track_foreground)

    def locate(self):
        if self.busy:return
        found=game_window() or (describe(self.last_foreground['hwnd']) if self.last_foreground else None)
        if not found:self.status.set('未找到游戏窗口：请先切到游戏再点“定位游戏”，或使用“框选区域”。');return
        self.last_foreground=found
        self.mode='window';self.region=None;self.sample=None;self.persist();self.update_target()
        self.status.set(f'已定位：{found["title"]}。按 A 开始识别。')

    def set_busy(self,busy):
        self.busy=busy
        for button in (self.scan_btn,self.chip_btn,self.select_btn,self.locate_btn):button.configure(state='disabled' if busy else 'normal')
        self.chip_btn.configure(text='…' if busy else 'A 识别')

    def restore(self):
        if not self.closed:
            self.root.deiconify();self.root.attributes('-topmost',True)

    def choose_region(self):
        if self.busy:return
        self.set_busy(True);self.status.set('请框选完整游戏内容，Enter 确认，Esc 取消。')
        self.root.withdraw();self.root.after(240,self.select_after_hide)

    def select_after_hide(self):
        try:
            with mss.mss() as capture:
                screen=capture.monitors[0]
                image=np.asarray(capture.grab(screen))[:,:,:3].copy()
            x,y,w,h=select_region(image,'Select full game; ENTER confirms; ESC cancels')
            self.region=dict(left=screen['left']+x,top=screen['top']+y,width=w,height=h)
            self.mode='region';self.sample=None;self.persist();self.update_target()
            self.status.set('范围已保存。按 A 读取画面。')
        except Exception as exc:self.status.set('未更改截图范围：'+str(exc))
        finally:self.restore();self.set_busy(False)

    def current_target(self):
        if self.sample:return None,None
        found=game_window() or (describe(self.last_foreground['hwnd']) if self.last_foreground else None)
        if self.mode=='region' and self.region:return None,self.region
        if found:return found,found['region']
        return None,None

    def scan(self):
        if self.busy:return
        try:
            if self.sample:found,region=None,None
            else:found,region=self.current_target()
            if not self.sample and region is None:raise ValueError('请先打开游戏并切到游戏窗口，或点击“框选区域”。')
            self.set_busy(True)
            self.recommendation.set('正在读取本次画面…')
            self.ev.delete(*self.ev.get_children())
            if found and self.mode=='window' and not self.sample:
                self.status.set('正在读取游戏窗口…');self.root.update_idletasks()
                frame=grab_window(found['hwnd'])
                if frame is not None:
                    self.status.set('正在识别…')
                    threading.Thread(target=self.process,args=(frame,False,found['hwnd']),daemon=True).start()
                    return
                self.status.set('窗口读取失败，改用屏幕截图…')
            self.status.set('正在截图…')
            self.root.withdraw()
            if found:focus_window(found['hwnd'])
            self.root.after(260,lambda:self.capture_once(region))
        except Exception as exc:self.status.set(str(exc));self.set_busy(False);self.expand()

    def capture_once(self,region):
        if self.closed:return
        try:
            if self.sample:frame=load_image(self.sample)
            else:
                try:ctypes.windll.dwmapi.DwmFlush()
                except (OSError,AttributeError):pass
                with mss.mss() as capture:frame=np.asarray(capture.grab(region))[:,:,:3].copy()
            self.restore();self.status.set('正在识别…')
            threading.Thread(target=self.process,args=(frame,),daemon=True).start()
        except Exception as exc:self.restore();self.status.set('截图失败：'+str(exc));self.set_busy(False)

    def read_frame(self,frame,trim=True):
        if trim:frame=trim_titlebar(frame)
        name,layout=load_layout(ROOT/'layouts.json',frame,'auto')
        if self.reader is None or self.reader_layout!=name:
            self.reader=Reader(layout);self.reader_layout=name
        result=self.reader.scan(frame);result['layout']=name
        return result

    def process(self,frame,trim=True,hwnd=None):
        try:
            result=self.read_frame(frame,trim)
            # The pot number fades in during chip animations; re-read only that box.
            board_shown=any(c.get('card') or c.get('status')=='unreadable' for c in result['board_cards'])
            for _ in range(3):
                if result['pot'] is not None or not hwnd or not board_shown:break
                time.sleep(.25)
                fresh=grab_window(hwnd)
                if fresh is None:break
                result['pot']=self.reader.pot(fresh)
            self.events.put(('ocr',result))
            advice=analyze(result,lambda text:self.events.put(('status',text)))
            result['advice']=advice
            if self.save_settings:write_json(DATA/'results'/'latest.json',result)
            self.events.put(('done',result))
        except Exception as exc:
            self.events.put(('error',str(exc)))
            if self.save_settings:
                try:
                    (DATA/'results').mkdir(exist_ok=True)
                    (DATA/'results'/'popup-error.log').write_text(traceback.format_exc(),encoding='utf-8')
                except OSError:pass

    def render_ocr(self,result):
        b=result.get('blinds');p=result.get('pot')
        pot='未知' if not p else (('约 ' if p.get('approximate') else '')+p['display'])
        self.money.set(f"底池 {pot}    盲注 {str(b['small'])+'/'+str(b['big']) if b else '未知'}    {price_text(result)}")
        self.cards.set('手牌 '+' '.join(c['card'] or '—' for c in result['hero_cards'])+'    公牌 '+' '.join(c['card'] or '—' for c in result['board_cards']))
        self.seats.delete(*self.seats.get_children())
        for s in result['seats']:
            self.seats.insert('',tk.END,values=(seat_label(s),
                s['stack']['display'] if s['stack'] else '未读到',
                s['displayed_bet']['display'] if s['displayed_bet'] else '—',
                ACTIONS.get(s['action'],'—')))
        self.recommendation.set('牌面已读取，正在自动分析…')

    def render_advice(self,result):
        self.last_result=result;advice=result['advice']
        self.render_ocr(result)
        self.ev.delete(*self.ev.get_children())
        if advice['status']!='ok':
            self.recommendation.set('暂不建议：'+advice['message'])
            self.equity.set('胜率 —')
            self.expand();return
        rec=advice['recommendation'];context=advice['context']
        b=result.get('blinds')
        self.money.set(f"底池 {context['pot']:,}    盲注 {str(b['small'])+'/'+str(b['big']) if b else '未知'}    {price_text(result)}")
        frequency=f"（频率 {rec['frequency']*100:.0f}%）" if rec.get('frequency') is not None else ''
        close=f"   和「{advice['close']['label']}」差不多" if advice.get('close') else ''
        self.recommendation.set('建议 '+rec['label']+frequency+close)
        need=f"  跟注需 {advice['required_equity']*100:.0f}%" if context['call'] else ''
        self.equity.set(f"胜率 {advice['equity']*100:.0f}%{need}")
        gto=advice['mode']=='gto'
        self.ev.configure(displaycolumns=('action','ev','bb','freq') if gto else ('action','ev','bb'))
        for a in advice['actions']:
            freq='—' if a.get('frequency') is None else f"{a['frequency']*100:.0f}%"
            self.ev.insert('',tk.END,values=(a['label'],format_chips(a['ev'],signed=True),f"{a['ev_bb']:+.1f}",freq),
                           tags=('best',) if a is rec else ())
        self.expand()

    def poll(self):
        if self.closed:return
        try:
            while True:
                kind,data=self.events.get_nowait()
                if kind=='ocr':self.render_ocr(data)
                elif kind=='hotkey':self._run_hotkey(data)
                elif kind=='status':self.status.set(data)
                elif kind=='done':
                    self.render_advice(data);self.set_busy(False)
                    timestamp=datetime.fromisoformat(data['captured_at']).astimezone().strftime('%H:%M:%S')
                    advice=data['advice'];seconds=(data.get('elapsed_ms',0)+advice.get('elapsed_ms',0))/1000
                    parts=[f'画面 {timestamp}',f'用时 {seconds:.1f} 秒']
                    if advice['status']=='ok':
                        parts.insert(0,f"{advice['mode_label']} · {advice['context']['opponents']} 位对手")
                    self.status.set(' · '.join(parts)+' · 按 A 再识别，按 Q 收起')
                elif kind=='error':
                    self.recommendation.set('本次分析失败，请重试')
                    self.status.set(data);self.set_busy(False);self.expand()
        except queue.Empty:pass
        self.root.after(80,self.poll)

    def auto_scan(self):
        """Read the current table once when the window opens, then stay click-driven."""
        if self.closed or self.busy:return
        if not self.sample and not (game_window() or self.last_foreground):return
        self.scan()

    def show_assumptions(self):
        advice=(self.last_result or {}).get('advice')
        if not advice:messagebox.showinfo('计算依据','先点击“识别一次”。',parent=self.root);return
        if advice['status']!='ok':messagebox.showinfo('本次未能计算',advice['message'],parent=self.root);return
        context=advice['context']
        text=advice['mode_label']+'\n\n'+'\n\n'.join(context['assumptions'])
        text+='\n\nEV：'+advice['ev_reference']
        if advice['mode']=='gto':text+=f"\n剩余可利用度：{advice['exploitability']:.3f} 筹码；收敛：{advice['converged']}"
        text+='\n\n自动范围：\n'+'\n'.join(k+': '+v for k,v in context['ranges_by_seat'].items())
        messagebox.showinfo('计算依据与限制',text,parent=self.root)

    def _install_hotkey(self):
        """A and Q work while Poker Fate is the front window, so the mouse stays on the table.

        The hook lives on its own thread. Installing it on the Tk thread crashes:
        the callback runs while Tk has released the GIL.
        """
        self._hook=None;self._hook_thread_id=None;self._held=set();self._swallow=set()
        self._hook_proc=_HOOKPROC(self._key_hook)
        threading.Thread(target=self._hotkey_loop,daemon=True).start()

    def _hotkey_loop(self):
        self._hook_thread_id=kernel32.GetCurrentThreadId()
        self._hook=user.SetWindowsHookExW(WH_KEYBOARD_LL,self._hook_proc,None,0) or None
        if not self._hook:
            self.events.put(('status','快捷键没装上，仍可点按钮识别。'));return
        msg=wintypes.MSG()
        while user.GetMessageW(ctypes.byref(msg),None,0,0)>0:
            user.TranslateMessage(ctypes.byref(msg));user.DispatchMessageW(ctypes.byref(msg))
        if self._hook:
            user.UnhookWindowsHookEx(self._hook);self._hook=None

    def _remove_hotkey(self):
        if getattr(self,'_hook_thread_id',None):
            user.PostThreadMessageW(self._hook_thread_id,WM_QUIT,0,0)

    def _on_destroy(self,event):
        if event.widget is self.root:
            self.closed=True;self._remove_hotkey()

    def _at_table(self):
        """Called from the hook thread, so it must not touch Tk."""
        hwnd=user.GetForegroundWindow()
        if not hwnd:return False
        pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value==self.own_pid:return True
        info=describe(hwnd)
        return bool(info and game_title(info['title']))

    def _key_hook(self,nCode,wParam,lParam):
        try:
            if nCode>=0 and not self.closed and self._on_key(wParam,lParam):return 1
        except Exception:pass
        return user.CallNextHookEx(self._hook,nCode,wParam,lParam)

    def _on_key(self,wParam,lParam):
        if wParam not in (WM_KEYDOWN,WM_KEYUP,WM_SYSKEYDOWN,WM_SYSKEYUP):return False
        info=ctypes.cast(lParam,ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        vk=info.vkCode
        if vk not in (VK_A,VK_Q):return False
        if wParam in (WM_KEYUP,WM_SYSKEYUP) or info.flags&LLKHF_UP:
            swallow=vk in self._swallow
            self._held.discard(vk);self._swallow.discard(vk)
            return swallow
        if vk in self._held:return vk in self._swallow
        self._held.add(vk)
        action=hotkey_action(vk,modifiers=_modifiers_down(),typing=_typing(),
                             game_focused=self._at_table(),panel_open=self.expanded)
        if not action:
            self._swallow.discard(vk);return False
        self._swallow.add(vk)
        self.events.put(('hotkey',action))
        return True

    def _run_hotkey(self,action):
        if self.closed:return
        if action=='scan':self.scan()
        elif action=='collapse' and self.expanded:self.collapse()

    def close(self):
        self.closed=True;self._remove_hotkey();self.root.destroy()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--sample',help='用自己的截图测试，仍需点击才识别')
    parser.add_argument('--version',action='version',version=VERSION)
    parser.add_argument('--diagnostics',metavar='JSON',help='运行离线资源和计算引擎检查，将结果写入 JSON 后退出')
    args=parser.parse_args()
    if args.diagnostics:
        from diagnostics import run
        report=run()
        write_json(args.diagnostics,report)
        raise SystemExit(0 if report['ok'] else 1)
    enable_dpi();root=tk.Tk();app=PokerPopup(root,sample=args.sample)
    root.mainloop()

if __name__=='__main__':main()

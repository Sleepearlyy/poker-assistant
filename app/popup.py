"""Always-on-top, click-to-capture poker assistant. No periodic screen capture.

The window hides only for the moment of the screenshot, then shows the OCR
result plus the local solver's action frequencies and chip EVs.
"""
import argparse
import ctypes
import os
from ctypes import wintypes
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont
import traceback

import mss
import cv2
import numpy as np
from reader import DATA, ROOT, Reader, enable_dpi, load_image, load_layout, trim_titlebar, write_json
from advisor import analyze
from core import format_chips
from app_info import VERSION

ACTIONS={'fold':'弃牌','check':'过牌','call':'跟注','bet':'下注','raise':'加注','all_in':'全下',
         'small_blind':'小盲','big_blind':'大盲'}

def display_amount(result,value):
    big=(result.get('blinds') or {}).get('big')
    bb=(result.get('pot') or {}).get('unit')=='bb' or any(
        (s.get('stack') or {}).get('unit')=='bb' for s in result.get('seats',[]))
    if bb and big:
        return f'{value/big:.2f}'.rstrip('0').rstrip('.')+'BB'
    return format_chips(value)

def display_action(result,action):
    label=ACTIONS.get(action['action'],action['action'])
    return label+' '+display_amount(result,action['amount']) if action.get('amount') else label

def price_text(result):
    """Call, check, or all-in. A short stack often has no separate call button."""
    controls=result.get('controls') or {}
    source=controls.get('source')
    amount=controls.get('to_call')
    if source=='preaction_buttons':return '等待轮到自己'
    if source=='check_button':return '过牌'
    if source in ('all_in_button','all_in_for_stack'):
        return '全下' if amount is None else '全下 '+display_amount(result,amount)
    return '跟注 未知' if amount is None else '跟注 '+display_amount(result,amount)

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
user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
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
    mem=0;bmp=0;original=0
    try:
        mem=gdi32.CreateCompatibleDC(hdc);bmp=gdi32.CreateCompatibleBitmap(hdc,w,h)
        if not mem or not bmp:return None
        original=gdi32.SelectObject(mem,bmp)
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
        if original:gdi32.SelectObject(mem,original)
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
    return ''.join(title.casefold().split()) == 'pokerfate'

def game_window():
    """Find Poker Fate, never use an unrelated foreground window as a fallback."""
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

class MONITORINFO(ctypes.Structure):
    _fields_=[('cbSize',wintypes.DWORD),('rcMonitor',wintypes.RECT),
              ('rcWork',wintypes.RECT),('dwFlags',wintypes.DWORD)]

user.MonitorFromWindow.argtypes=[wintypes.HWND,wintypes.DWORD]
user.MonitorFromWindow.restype=wintypes.HANDLE
user.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.POINTER(MONITORINFO)]

def work_area(root, hwnd=None):
    hwnd=hwnd or user.GetAncestor(int(root.winfo_id()),GA_ROOT)
    info=MONITORINFO();info.cbSize=ctypes.sizeof(info)
    monitor=user.MonitorFromWindow(hwnd,2)
    if monitor and user.GetMonitorInfoW(monitor,ctypes.byref(info)):
        r=info.rcWork
        return r.left,r.top,r.right,r.bottom
    return 0,0,root.winfo_screenwidth(),root.winfo_screenheight()

class PokerPopup:
    def __init__(self,root,*,sample=None,save_settings=True):
        self.root=root;self.sample=sample;self.save_settings=save_settings
        self.events=queue.Queue();self.busy=False;self.closed=False;self.expanded=False
        self.reader=None;self.reader_layout=None;self.last_result=None
        self.preview=None
        self.last_foreground=game_window()
        self.own_pid=os.getpid()
        self.own_hwnd=user.GetAncestor(int(root.winfo_id()),GA_ROOT)
        root.title(f'德扑助手 {VERSION} · 点击识别');root.attributes('-topmost',True)
        root.configure(bg='#111318');root.resizable(True,True)
        root.protocol('WM_DELETE_WINDOW',self.close)
        style=ttk.Style(root);style.theme_use('clam')
        style.configure('.',background='#111318',foreground='#f5f6fa',bordercolor='#292d38',
                        lightcolor='#111318',darkcolor='#111318',troughcolor='#111318')
        style.configure('TFrame',background='#111318')
        style.configure('TLabel',background='#111318',foreground='#f5f6fa',font=('Microsoft YaHei UI',9))
        style.configure('Muted.TLabel',foreground='#b8c0cf',font=('Microsoft YaHei UI',8))
        style.configure('TButton',background='#272b35',foreground='#f1f3f8',borderwidth=0,
                        relief='flat',padding=(8,4),font=('Microsoft YaHei UI',8))
        style.map('TButton',background=[('pressed','#363c4c'),('active','#323847')],
                  foreground=[('disabled','#697183')])
        style.configure('Accent.TButton',font=('Microsoft YaHei UI',8,'bold'),background='#245d99',foreground='#ffffff')
        style.map('Accent.TButton',background=[('disabled','#343641'),('pressed','#1d4e83'),('active','#2f70b4')],
                  foreground=[('disabled','#b8c0cf'),('!disabled','#ffffff')])
        style.configure('TMenubutton',background='#272b35',foreground='#f1f3f8',borderwidth=0,padding=(6,4),font=('Microsoft YaHei UI',8))
        style.map('TMenubutton',background=[('active','#323847')])
        style.configure('TNotebook',background='#111318',borderwidth=0,tabmargins=(0,4,0,0))
        style.configure('TNotebook.Tab',background='#111318',foreground='#b8c0cf',borderwidth=0,
                        padding=(12,4),font=('Microsoft YaHei UI',8))
        style.map('TNotebook.Tab',background=[('selected','#272b35'),('active','#20242d')],
                  foreground=[('selected','#a8d8ff'),('active','#f5f6fa')])
        for orientation in ('Vertical','Horizontal'):
            name=orientation+'.TScrollbar'
            style.configure(name,background='#383e4b',troughcolor='#111318',borderwidth=0,
                            arrowsize=9,width=8,gripcount=0)
            style.map(name,background=[('active','#535c70'),('pressed','#69758e')])
            style.layout(name,[(orientation+'.Scrollbar.trough',{'sticky':'nswe','children':[
                (orientation+'.Scrollbar.thumb',{'expand':'1','sticky':'nswe'})]})])
        rowheight=tkfont.Font(root,font=('Microsoft YaHei UI',9)).metrics('linespace')+3
        style.configure('Treeview',background='#1d2028',fieldbackground='#1d2028',foreground='#f1f3f8',rowheight=rowheight,font=('Microsoft YaHei UI',9),borderwidth=0,relief='flat')
        style.configure('Treeview.Heading',background='#252935',foreground='#d0d7e5',font=('Microsoft YaHei UI',8),padding=(4,3),borderwidth=0,relief='flat')
        style.map('Treeview',background=[('selected','#233549')])
        style.map('Treeview.Heading',background=[('active','#2d3240')])
        self.outer=ttk.Frame(root,padding=(12,10));self.outer.pack(fill='both',expand=True)
        self.chip=ttk.Frame(self.outer)
        self.chip_btn=ttk.Button(self.chip,text='A 识别',style='Accent.TButton',command=self.scan)
        self.chip_btn.pack(fill='both',expand=True)
        self.chip_menu=tk.Menu(root,tearoff=0)
        self.chip_menu.add_command(label='退出',command=self.close)
        self.chip_btn.bind('<Button-3>',lambda event:self.chip_menu.tk_popup(event.x_root,event.y_root))
        self.panel=ttk.Frame(self.outer)
        self.canvas=tk.Canvas(self.panel,bg='#111318',highlightthickness=0,width=1,height=1)
        self.scroll=ttk.Scrollbar(self.panel,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side='right',fill='y');self.canvas.pack(side='left',fill='both',expand=True)
        self.body=ttk.Frame(self.canvas)
        self.body_id=self.canvas.create_window(0,0,window=self.body,anchor='nw')
        self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',self.reflow)
        self.root.bind('<MouseWheel>',self.scroll_panel,add='+')
        header=ttk.Frame(self.body);self.header=header;header.pack(fill='x')
        self.scan_btn=ttk.Button(header,text='识别 A',width=6,style='Accent.TButton',command=self.scan)
        self.locate_btn=ttk.Button(header,text='定位',width=4,command=self.locate)
        self.toggle_btn=ttk.Button(header,text='收起 Q',width=6,command=self.collapse)
        more=ttk.Menubutton(header,text='更多',width=3)
        menu=tk.Menu(more,tearoff=0,bg='#252935',fg='#f1f3f8',activebackground='#233549',activeforeground='#ffffff',borderwidth=0)
        menu.add_command(label='计算依据',command=self.show_assumptions)
        menu.add_separator();menu.add_command(label='退出',command=self.close)
        more.configure(menu=menu)
        self.toolbar=[self.scan_btn,self.locate_btn,self.toggle_btn,more]
        self.status=tk.StringVar(value='')
        self.target=tk.StringVar();self.update_target()
        self.details=ttk.Frame(self.body);self.details.pack(fill='both',expand=True)
        self.money=tk.StringVar(value='底池 —')
        self.cards=tk.StringVar(value='手牌 —    公牌 —')
        self.equity=tk.StringVar(value='胜率 —')
        self.recommendation=tk.StringVar(value='识别后自动分析')
        self.wrap_labels=[]
        for variable,options in [
            (self.money,{'font':('Microsoft YaHei UI',9)}),
            (self.cards,{'font':('Segoe UI Symbol',10)}),
            (self.equity,{'font':('Microsoft YaHei UI',9),'foreground':'#f1f3f8'}),
            (self.recommendation,{'font':('Microsoft YaHei UI',10,'bold'),'foreground':'#a8d8ff'})]:
            label=ttk.Label(self.details,textvariable=variable,anchor='w',justify='left',wraplength=500,**options)
            label.pack(fill='x',padx=4,pady=(3,0));self.wrap_labels.append(label)
        self.tables=ttk.Notebook(self.details);self.tables.pack(fill='both',expand=True,pady=(3,0))
        self.table_frames=[];self.table_widths=[]
        for name,columns in [('seats',[('seat','位置',84),('stack','后手',64),('bet','下注',58),('action','动作',54)]),
                             ('ev',[('action','候选动作',104),('ev','EV 筹码',70),('bb','EV 大盲',58),('freq','频率',44)])]:
            frame=ttk.Frame(self.tables);self.table_frames.append(frame)
            self.tables.add(frame,text='牌桌' if name=='seats' else '动作 EV')
            tree=ttk.Treeview(frame,columns=tuple(c[0] for c in columns),show='headings',height=6,selectmode='none')
            setattr(self,name,tree)
            scale=float(root.tk.call('tk','scaling'))/(96/72)
            widths=[]
            for col,title,width in columns:
                width=round(width*scale);widths.append(width)
                tree.heading(col,text=title);tree.column(col,width=width,minwidth=width,anchor='center',stretch=True)
            self.table_widths.append(sum(widths)+24)
            ys=ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
            xs=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
            tree.configure(yscrollcommand=ys.set,xscrollcommand=xs.set)
            tree.grid(row=0,column=0,sticky='nsew');ys.grid(row=0,column=1,sticky='ns')
            xs.grid(row=1,column=0,sticky='ew');frame.columnconfigure(0,weight=1);frame.rowconfigure(0,weight=1)
        self.ev.tag_configure('best',foreground='#a8d8ff',background='#233549')
        self.ev.configure(displaycolumns=('action','bb'))
        status_label=ttk.Label(self.details,textvariable=self.status,style='Muted.TLabel',justify='left',wraplength=400)
        status_label.pack(fill='x',pady=(2,0),before=self.tables);self.wrap_labels.append(status_label)
        self.collapse()
        root.deiconify();root.state('normal');root.update();self.position()
        self.dark_titlebar(root)
        root.lift();root.attributes('-topmost',True)
        root.bind('<Destroy>',self._on_destroy)
        self._install_hotkey()
        root.after(50,self.position);root.after(80,self.poll);root.after(250,self.track_foreground)

    def scroll_panel(self,event):
        if self.expanded and event.widget not in (self.seats,self.ev):
            self.canvas.yview_scroll(-int(event.delta/120),'units')
            return 'break'

    def reflow(self,event=None):
        if not self.expanded:return
        width=max(1,event.width if event else self.canvas.winfo_width())
        self.canvas.itemconfigure(self.body_id,width=width)
        for label in self.wrap_labels:label.configure(wraplength=max(1,width-8))
        cell=max(button.winfo_reqwidth() for button in self.toolbar)+6
        count=max(1,min(len(self.toolbar),width//cell))
        for index in range(len(self.toolbar)):self.header.columnconfigure(index,weight=0,uniform='')
        for index,button in enumerate(self.toolbar):
            button.grid(row=index//count,column=index%count,sticky='ew',padx=(0,4),pady=2)
        for index in range(count):self.header.columnconfigure(index,weight=1,uniform='buttons')

    def position(self):
        target=(self.last_foreground or {}).get('hwnd')
        l,t,r,b=work_area(self.root,target)
        self.root.update_idletasks()
        if not self.expanded:
            width,height=self.chip.winfo_reqwidth()+6,self.chip.winfo_reqheight()+6
        else:
            scale=float(self.root.tk.call('tk','scaling'))/(96/72)
            width=min(round(380*scale),round((r-l)*.22))
            self.root.geometry(f'{width}x200')
            self.root.update_idletasks();self.reflow();self.root.update_idletasks()
            height=min(self.body.winfo_reqheight()+12,round((b-t)*.32))
        self.root.geometry(f'{width}x{height}')
        self.root.update_idletasks()
        # Tk geometry is client size; SetWindowPos must not shrink it to outer size.
        hwnd=user.GetAncestor(int(self.root.winfo_id()),GA_ROOT)
        rect=wintypes.RECT();user.GetWindowRect(hwnd,ctypes.byref(rect))
        x=l+16;y=max(t+8,b-(rect.bottom-rect.top)-16)
        user.SetWindowPos(hwnd,-1,x,y,0,0,0x0041)  # SHOWWINDOW | NOSIZE
        self.root.attributes('-topmost',True)

    def collapse(self):
        self.expanded=False
        self.panel.pack_forget()
        self.outer.configure(padding=(3,3))
        self.chip.pack(fill='both',expand=True)
        self.root.overrideredirect(True)
        self.position()

    def expand(self):
        self.expanded=True
        self.chip.pack_forget()
        self.outer.configure(padding=(6,4))
        self.root.overrideredirect(False)
        self.panel.pack(fill='both',expand=True)
        self.position();self.canvas.yview_moveto(0)
        self.dark_titlebar(self.root)
        self.root.lift()

    @staticmethod
    def dark_titlebar(window):
        try:
            hwnd=user.GetAncestor(int(window.winfo_id()),GA_ROOT)
            enabled=ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd),20,ctypes.byref(enabled),ctypes.sizeof(enabled))
        except (OSError,AttributeError):pass

    def update_target(self):
        found=self.last_foreground
        if self.sample:text='示例图片测试'
        elif found:
            r=found['region'];text=f"Poker Fate · 游戏内容区 {r['width']} × {r['height']}"
        else:text='未找到 Poker Fate，请打开游戏并取消最小化。'
        self.target.set(text)

    def track_foreground(self):
        if self.closed:return
        try:
            found=game_window()
            if found!=self.last_foreground:
                self.last_foreground=found;self.update_target()
            area=work_area(self.root)
            if area!=getattr(self,'_work_area',None):
                if hasattr(self,'_work_area'):self.position()
                self._work_area=work_area(self.root)
        except OSError:pass
        self.root.after(800,self.track_foreground)

    def locate(self):
        if self.busy:return
        self.close_preview()
        self.last_foreground=game_window();self.sample=None;self.update_target()
        if not self.last_foreground:
            self.status.set('请打开 Poker Fate 并取消最小化。');self.expand();return
        found=self.last_foreground
        frame=grab_window(found['hwnd'])
        if frame is not None:
            self.show_preview(frame);return
        self.set_busy(True);self.root.withdraw();focus_window(found['hwnd'])
        self.root.after(260,lambda:self.capture_once(found['hwnd'],preview=True))

    def close_preview(self):
        if self.preview is not None:
            self.preview.destroy();self.preview=None
            self.restore()

    def show_preview(self,frame):
        self.close_preview()
        h,w=frame.shape[:2]
        l,t,r,b=work_area(self.root,(self.last_foreground or {}).get('hwnd'))
        max_width=max(1,min(600,round((r-l)*.38))-24)
        max_height=max(1,round((b-t)*.36)-100)
        scale=min(max_width/w,max_height/h,1.)
        thumb=cv2.resize(frame,(max(1,round(w*scale)),max(1,round(h*scale))),interpolation=cv2.INTER_AREA)
        ok,encoded=cv2.imencode('.png',thumb)
        if not ok:raise ValueError('截图预览生成失败')
        win=tk.Toplevel(self.root);self.preview=win
        self.root.withdraw()
        win.title('游戏窗口预览');win.configure(bg='#111318');win.attributes('-topmost',True)
        win.resizable(False,False);win.protocol('WM_DELETE_WINDOW',self.close_preview)
        body=ttk.Frame(win,padding=12);body.pack(fill='both',expand=True)
        ttk.Label(body,text=f'Poker Fate  ·  {w} × {h}',font=('Microsoft YaHei UI',9,'bold')).pack(anchor='w',pady=(0,8))
        win.photo=tk.PhotoImage(master=win,data=encoded.tobytes())
        tk.Label(body,image=win.photo,bg='#111318',borderwidth=0).pack()
        footer=ttk.Frame(body);footer.pack(fill='x',pady=(10,0))
        ttk.Button(footer,text='刷新截图',command=self.locate).pack(side='left')
        ttk.Button(footer,text='确认范围',style='Accent.TButton',command=self.confirm_preview).pack(side='right')
        win.update_idletasks()
        win.geometry(f'+{l+16}+{max(t+8,b-win.winfo_reqheight()-50)}')
        self.dark_titlebar(win);win.lift()
        self.status.set('已定位游戏内容区，可在预览中核对范围。')

    def confirm_preview(self):
        self.close_preview();self.status.set('已确认游戏窗口，按 A 识别。')

    def set_busy(self,busy):
        self.busy=busy
        for button in (self.scan_btn,self.chip_btn,self.locate_btn):button.configure(state='disabled' if busy else 'normal')
        self.chip_btn.configure(text='…' if busy else 'A 识别')

    def restore(self):
        if not self.closed:
            self.root.deiconify();self.root.attributes('-topmost',True)

    def current_target(self):
        if self.sample:return None,None
        found=game_window()
        self.last_foreground=found;self.update_target()
        return (found,found['region']) if found else (None,None)

    def scan(self):
        if self.busy:return
        self.close_preview()
        self.last_result=None
        self.ev.delete(*self.ev.get_children())
        self.seats.delete(*self.seats.get_children())
        self.money.set('底池 —');self.cards.set('手牌 —    公牌 —');self.equity.set('胜率 —')
        self.recommendation.set('正在读取本次画面…')
        try:
            if self.sample:found,region=None,None
            else:found,region=self.current_target()
            if not self.sample and region is None:raise ValueError('未找到 Poker Fate，请打开游戏并取消最小化。')
            self.set_busy(True)
            self.recommendation.set('正在读取本次画面…')
            self.ev.delete(*self.ev.get_children())
            if found and not self.sample:
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
            self.root.after(260,lambda:self.capture_once(found['hwnd'] if found else None))
        except Exception as exc:
            self.recommendation.set('未读取到游戏画面')
            self.status.set(str(exc));self.set_busy(False);self.expand()

    def capture_once(self,hwnd,preview=False):
        if self.closed:return
        try:
            if self.sample:frame=load_image(self.sample)
            else:
                try:ctypes.windll.dwmapi.DwmFlush()
                except (OSError,AttributeError):pass
                found=describe(hwnd)
                if not found or not game_title(found['title']):
                    raise ValueError('Poker Fate 已关闭或最小化，请恢复游戏后重试。')
                if user.GetForegroundWindow()!=hwnd:
                    raise ValueError('请将 Poker Fate 切到前台后重试。')
                region=found['region']
                with mss.mss() as capture:
                    screen=capture.monitors[0]
                    if (region['left']<screen['left'] or region['top']<screen['top'] or
                        region['left']+region['width']>screen['left']+screen['width'] or
                        region['top']+region['height']>screen['top']+screen['height']):
                        raise ValueError('请将游戏窗口完整移回屏幕内后重试。')
                    frame=np.asarray(capture.grab(region))[:,:,:3].copy()
            self.restore()
            if preview:
                self.set_busy(False);self.show_preview(frame);return
            self.status.set('正在识别…')
            threading.Thread(target=self.process,args=(frame,bool(self.sample)),daemon=True).start()
        except Exception as exc:
            self.recommendation.set('未读取到游戏画面')
            self.restore();self.status.set('截图失败：'+str(exc));self.set_busy(False);self.expand()

    def read_frame(self,frame,trim=True):
        if trim:frame=trim_titlebar(frame)
        name,layout=load_layout(ROOT/'layouts.json',frame,'auto')
        if self.reader is None or self.reader_layout!=name:
            self.reader=Reader(layout);self.reader_layout=name
        else:self.reader.layout=layout
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
        p=result.get('pot')
        pot='未知' if not p else (('约 ' if p.get('approximate') else '')+p['display'])
        self.money.set(f"底池 {pot}    {price_text(result)}")
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
        self.tables.select(self.table_frames[1])
        if advice['status']!='ok':
            self.recommendation.set('暂不建议：'+advice['message'])
            self.equity.set('胜率 —')
            self.expand();return
        rec=advice['recommendation'];context=advice['context']
        self.money.set(f"底池 {display_amount(result,context['pot'])}    {price_text(result)}")
        frequency=f"（频率 {rec['frequency']*100:.0f}%）" if rec.get('frequency') is not None else ''
        self.recommendation.set('建议 '+display_action(result,rec)+frequency)
        need=f"  跟注需 {advice['required_equity']*100:.0f}%" if context['call'] else ''
        self.equity.set(f"胜率 {advice['equity']*100:.0f}%{need}")
        gto=advice['mode']=='gto'
        self.ev.configure(displaycolumns=('action','bb','freq') if gto else ('action','bb'))
        for a in advice['actions']:
            freq='—' if a.get('frequency') is None else f"{a['frequency']*100:.0f}%"
            self.ev.insert('',tk.END,values=(display_action(result,a),format_chips(a['ev'],signed=True),f"{a['ev_bb']:+.1f}",freq),
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
                    advice=data['advice']
                    if advice['status']=='ok':
                        mode='估算 · 非 GTO' if advice['mode']=='estimate' else advice['mode_label']
                        self.status.set(f"{mode} · {advice['context']['opponents']} 位对手")
                    else:self.status.set('')
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
    args=parser.parse_args()
    enable_dpi();root=tk.Tk();app=PokerPopup(root,sample=args.sample)
    root.mainloop()

if __name__=='__main__':main()

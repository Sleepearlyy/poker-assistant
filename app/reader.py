"""Poker Fate screen reader. Local OCR only; no game input or strategy."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR
from core import numeric, blinds, action, card_rank, Stability, visible_pot, assign_roles, facing_button
from paths import DATA, ROOT
import re

def load_image(path):
    frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"Cannot read image: {path}")
    return frame

def save_image(path, frame):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(path.suffix or '.png', frame)[1].tofile(str(path))

def trim_titlebar(frame):
    # Windows title bars can be light or coloured. Require a near-uniform horizontal band.
    n = 0
    for index, row in enumerate(frame[:min(65, frame.shape[0] // 10)]):
        median = np.median(row, axis=0)
        neutral = np.max(np.abs(row.astype(float)-median), axis=1) < 12
        if neutral.mean() < 0.75:
            if index < 2:
                n += 1
                continue
            break
        n += 1
    return frame[n:] if 15 <= n <= 60 else frame

def roi(frame, rect):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = rect
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise ValueError(f"Invalid normalized rectangle: {rect}")
    return frame[int(y1*h):max(int(y1*h)+1, int(y2*h)), int(x1*w):max(int(x1*w)+1, int(x2*w))]

def pad_rect(rect, pad):
    """Widen a crop horizontally; long stacks such as 245.32K overflow the preset box."""
    x1, y1, x2, y2 = rect
    return (max(0., x1-pad), y1, min(1., x2+pad), y2)

def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)

def suit_color(crop):
    """Four-color deck: red hearts, blue diamonds, green clubs, grey spades.

    The white rank is ignored so a large glyph does not dilute the background.
    """
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    background = ~((v > 170) & (s < 90))
    if float(background.mean()) < 0.25:
        return None
    masks = {'hearts': ((h < 12) | (h > 165)) & (s > 85) & (v > 100),
             'diamonds': (h > 92) & (h < 130) & (s > 70) & (v > 110),
             'clubs': (h > 35) & (h < 90) & (s > 70) & (v > 120),
             'spades': (s < 55) & (v > 25) & (v < 170)}
    fractions = {name: float(mask[background].mean()) for name, mask in masks.items()}
    suit = max(fractions, key=fractions.get)
    if fractions[suit] < (0.45 if suit == 'spades' else 0.23):
        return None
    return suit

def rank_glyph(crop):
    """Black rank on white, one image for every suit. OCR runs once on this."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, np.array([0, 0, 165]), np.array([179, 120, 255]))
    if float(white.mean()) < 0.015:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, white = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.cvtColor(255 - white, cv2.COLOR_GRAY2BGR)

def load_layout(path, frame, selected):
    layouts = json.loads(Path(path).read_text(encoding='utf-8'))
    ratio = frame.shape[1] / frame.shape[0]
    name = selected if selected != 'auto' else min(layouts, key=lambda k: abs(layouts[k]['aspect'] - ratio))
    if name not in layouts:
        raise ValueError(f"Unknown layout {name}; available: {list(layouts)}")
    if abs(ratio / layouts[name]['aspect'] - 1) > 0.12:
        raise ValueError('Game aspect ratio differs too much. Select only the complete game content, or calibrate a layout.')
    return name, layouts[name]

class Reader:
    def __init__(self, layout, debug=None):
        self.layout = layout
        self.debug = Path(debug) if debug else None
        self.ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2,
                            det_limit_type='max', det_limit_side_len=736)
        self.raw = {}

    def read_crop(self, crop, key, detection=True, scale=None):
        if crop.size == 0:
            return []
        scale = scale or min(4, max(2, 64 / crop.shape[0]))
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        crop = cv2.copyMakeBorder(crop, 12, 12, 12, 12, cv2.BORDER_REPLICATE)
        if self.debug:
            save_image(self.debug / (key + '.png'), crop)
        result, _ = self.ocr(crop, use_det=detection, use_cls=False, use_rec=True)
        lines = []
        for item in result or []:
            if len(item) == 3:
                box, text, score = item
                lines.append({'text': text, 'score': float(score), 'box': np.asarray(box).tolist()})
            elif len(item) == 2:
                text, score = item
                lines.append({'text': text, 'score': float(score)})
        self.raw[key] = lines
        return lines

    def read(self, frame, rect, key):
        return self.read_crop(roi(frame, rect), key)

    def pot(self, frame):
        return numeric(self.read(frame, self.layout['pot'], 'pot'))

    def read_fold(self, frame, rect, key):
        x1, y1, x2, y2 = rect
        # Big avatar boxes: the 弃牌 badge sits in the upper half and its text is large.
        if y2 - y1 > .12:
            return self.read_crop(roi(frame, [x1, y1, x2, y1 + (y2 - y1) / 2]), key, scale=1.5)
        return self.read(frame, rect, key)

    def stack(self, frame, rect, key):
        # Read a slightly wider box first: big stacks (245.32K) are wider than the
        # preset box and a clipped "K" turns a valid amount into None or a wrong number.
        value = numeric(self.read(frame, pad_rect(rect, .012), key + '_stack'))
        if value is None:
            value = numeric(self.read(frame, rect, key + '_stack_exact'))
        return value

    def card(self, frame, rect, key):
        crop = roi(frame, rect)
        suit = suit_color(crop)
        # No card-colored pixels: skip OCR. Empty slots used to be the slow part.
        if suit:
            glyph = rank_glyph(crop)
            rank = card_rank(self.read_crop(glyph, key, detection=False))
            # A pip under Q makes the whole crop look like "？". Detect the letter alone.
            if rank is None:
                rank = card_rank(self.read_crop(glyph, key + '_det', detection=True))
        else:
            rank = None
            self.raw[key] = []
        symbols = {'hearts': '♥', 'diamonds': '♦', 'clubs': '♣', 'spades': '♠'}
        status = 'recognized' if rank and suit else ('unreadable' if suit else 'unknown')
        return {'rank': rank['rank'] if rank else None, 'suit': suit if rank else None,
                'card': rank['rank'] + symbols[suit] if rank and suit else None,
                'confidence': rank['confidence'] if rank else None,
                'status': status,
                'suit_method': 'four_color_background' if rank and suit else None,
                'needs_sample_validation': False}

    def controls(self, frame):
        rect = self.layout.get('hero_controls')
        if not rect:
            return {'to_call': None, 'source': None, 'hero_turn': False}
        # Button labels are large: read unscaled first, and enlarge only when the
        # buttons or the smaller call amount were missed.
        crop = roi(frame, rect)
        found = None
        for scale in (1.0, None):
            lines = self.read_crop(crop, 'hero_controls', scale=scale)
            found = facing_button(' '.join(x['text'] for x in lines if x['score'] >= .8))
            if found['hero_turn'] and not (found['source'] == 'call_button' and found['to_call'] is None):
                break
        return found

    def dealer(self, frame):
        template_path = ROOT/'assets'/'dealer.png'
        if not template_path.exists() or not self.layout.get('dealer_anchors'):
            return None
        template = load_image(template_path)
        scale = frame.shape[1]/1920
        template = cv2.resize(template, None, fx=scale, fy=scale)
        h,w = frame.shape[:2]
        zone = frame[int(h*.25):int(h*.76), int(w*.15):int(w*.85)]
        score = cv2.matchTemplate(cv2.cvtColor(zone,cv2.COLOR_BGR2GRAY), cv2.cvtColor(template,cv2.COLOR_BGR2GRAY),cv2.TM_CCOEFF_NORMED)
        _, confidence, _, xy = cv2.minMaxLoc(score)
        if confidence < .75: return None
        x=(xy[0]+template.shape[1]/2+w*.15)/w
        y=(xy[1]+template.shape[0]/2+h*.25)/h
        anchors=self.layout['dealer_anchors']
        seat=min(anchors,key=lambda s:(anchors[s][0]-x)**2+(anchors[s][1]-y)**2)
        return {'seat':seat,'confidence':round(confidence,3)}

    def scan(self, frame):
        self.raw = {}
        start = time.perf_counter()
        result = {'captured_at': datetime.now(timezone.utc).isoformat(),
                  'image_size': [frame.shape[1], frame.shape[0]], 'seats': []}
        result['blinds'] = blinds(self.read(frame, self.layout['blinds'], 'blinds'))
        result['pot'] = self.pot(frame)
        result['bet_presets'] = []
        if result['pot'] and self.layout.get('bet_presets'):
            values=[numeric(self.read(frame, rect, 'preset_'+str(i))) for i,rect in enumerate(self.layout['bet_presets'])]
            expected=[1,2/3,1/2,1/3]
            if sum(v is not None and abs(v['value']-result['pot']['value']*f)<=max(2,result['pot']['value']*.01) for v,f in zip(values,expected))>=3:
                result['bet_presets']=sorted(v['value'] for v in values if v is not None)
        result['controls'] = self.controls(frame)
        result['dealer'] = self.dealer(frame)
        for seat in self.layout['seats']:
            key = seat['id']
            stack = self.stack(frame, seat['stack'], key)
            name = None
            if stack is None:
                name_lines = self.read(frame, seat['name'], key + '_name')
                name = ' '.join(x['text'] for x in name_lines if x['score'] >= 0.8) or None
            act = action(self.read(frame, seat['action'], key + '_action'))
            if seat.get('fold') and act['action'] != 'fold':
                folded = action(self.read_fold(frame, seat['fold'], key + '_fold'))
                if folded['action'] == 'fold':
                    act['action'] = 'fold'
            present = (stack is not None or name is not None or act['action'] is not None
                       or act['displayed_bet'] is not None)
            result['seats'].append({'seat': key, 'position': seat['label'],
                'presence': 'occupied' if present else 'empty_or_unreadable',
                'name': name, 'stack': stack,
                'action': act['action'] if present else None,
                'displayed_bet': act['displayed_bet'] if present else None,
                'blind_role': act['action'] if present and act['action'] in ('small_blind', 'big_blind') else None})
        controls = result['controls']
        if controls.get('source') == 'all_in_button' and controls.get('to_call') is None:
            hero = next((s for s in result['seats'] if s['seat'] == 'bottom'), None)
            stack = (hero or {}).get('stack')
            if stack:
                controls['to_call'] = stack['value']
        roles = assign_roles(result['seats'], (result.get('dealer') or {}).get('seat'))
        for seat in result['seats']:
            seat['role'] = roles.get(seat['seat'])
        result['recognized_players'] = sum(s['presence'] == 'occupied' for s in result['seats'])
        result['hero_cards'] = [self.card(frame, rect, 'hero_' + str(i+1)) for i, rect in enumerate(self.layout['hero_cards'])]
        result['board_cards'] = [self.card(frame, rect, 'board_' + str(i+1)) for i, rect in enumerate(self.layout['board_cards'])]
        if result['pot'] is None:
            result['pot'] = visible_pot(result)
        result['elapsed_ms'] = round((time.perf_counter() - start)*1000)
        result['raw_ocr'] = self.raw
        return result

def annotate(frame, layout):
    out = frame.copy()
    regions = [('blinds', layout['blinds']), ('pot', layout['pot'])]
    for seat in layout['seats']:
        regions.extend((seat['id'] + '.' + k, seat[k]) for k in ('stack', 'name', 'action', 'fold') if seat.get(k))
    regions.extend(('hero.'+str(i), r) for i, r in enumerate(layout['hero_cards']))
    regions.extend(('board.'+str(i), r) for i, r in enumerate(layout['board_cards']))
    h, w = out.shape[:2]
    for name, (x1, y1, x2, y2) in regions:
        p1, p2 = (int(x1*w), int(y1*h)), (int(x2*w), int(y2*h))
        cv2.rectangle(out, p1, p2, (0, 255, 255), 2)
        cv2.putText(out, name, (p1[0], max(14, p1[1]-3)), cv2.FONT_HERSHEY_SIMPLEX, .4, (0, 255, 255), 1)
    return out

def print_result(result):
    b = result['blinds']
    pot = result['pot']
    print(f"\n{result['captured_at']}  识别到 {result['recognized_players']} 人  耗时 {result['elapsed_ms']}ms")
    print(f"大小盲: {str(b['small'])+'/'+str(b['big']) if b else '未知'}  底池: {pot['display'] if pot else '未知'}")
    for seat in result['seats']:
        stack, bet = seat['stack'], seat['displayed_bet']
        where = seat.get('role') or ('空位' if seat['presence'] != 'occupied' else '在局')
        if seat['seat'] == 'bottom':
            where += ' · 自己'
        print(f"  {where}: 后手={stack['display'] if stack else '未知'}  "
              f"动作={seat['action'] or '未知'}  显示下注={bet['display'] if bet else '未知'}  "
              f"{seat['name'] or seat['presence']}")
    print('手牌: ' + ' '.join(c['card'] or '?' for c in result['hero_cards']))
    print('公牌: ' + ' '.join(c['card'] or '?' for c in result['board_cards']))

def select_region(frame, title='Select game content; ENTER confirms; ESC cancels'):
    scale = min(1., 1400/frame.shape[1], 800/frame.shape[0])
    shown = cv2.resize(frame, None, fx=scale, fy=scale)
    selected = cv2.selectROI(title, shown, showCrosshair=True, fromCenter=False)
    cv2.destroyAllWindows()
    x, y, w, h = [round(v/scale) for v in selected]
    if w < 3 or h < 3:
        raise ValueError('Selection cancelled or too small.')
    return x, y, w, h

def enable_dpi():
    if sys.platform == 'win32':
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (OSError, AttributeError):
            pass

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='德扑屏幕读取：筹码、动作、大小盲、底池、手牌、公牌')
    parser.add_argument('--config', default=str(ROOT/'layouts.json'))
    parser.add_argument('--layout', default='auto')
    modes = parser.add_subparsers(dest='mode', required=True)
    still = modes.add_parser('image', help='识别截图')
    still.add_argument('path')
    still.add_argument('--output', default=str(ROOT/'results'/'latest.json'))
    still.add_argument('--debug', help='保存识别区域和OCR原文')
    live = modes.add_parser('live', help='框选屏幕后循环识别；Ctrl+C停止')
    live.add_argument('--monitor', type=int, default=1)
    live.add_argument('--region', nargs=4, type=int, metavar=('LEFT','TOP','WIDTH','HEIGHT'))
    live.add_argument('--interval', type=float, default=0.5, help='最短帧间隔，推理较慢时以实际速度为准')
    live.add_argument('--delay', type=float, default=3, help='框选前等待秒数，便于切换到游戏')
    live.add_argument('--frames', type=int, default=0, help='0=持续运行')
    live.add_argument('--output', default=str(ROOT/'results'/'latest.json'))
    cal = modes.add_parser('calibrate', help='用截图校准某一个区域')
    cal.add_argument('path')
    cal.add_argument('field', help='pot/blinds/top.stack/top.name/top.action/hero.0/board.0')
    args = parser.parse_args()
    enable_dpi()
    if args.mode in ('image', 'calibrate'):
        frame = trim_titlebar(load_image(args.path))
        name, layout = load_layout(args.config, frame, args.layout)
        if args.mode == 'calibrate':
            x, y, w, h = select_region(frame, 'Select ' + args.field + '; ENTER confirms')
            fh, fw = frame.shape[:2]
            rect = [x/fw, y/fh, min((x+w)/fw, 1), min((y+h)/fh, 1)]
            if args.field in ('pot', 'blinds'):
                layout[args.field] = rect
            else:
                group, field = args.field.split('.')
                if group in ('hero', 'board'):
                    layout[group+'_cards'][int(field)] = rect
                else:
                    if field not in ('stack', 'name', 'action', 'fold'):
                        raise ValueError('Unknown seat field')
                    seat = next(s for s in layout['seats'] if s['id'] == group)
                    seat[field] = rect
            all_layouts = json.loads(Path(args.config).read_text(encoding='utf-8'))
            all_layouts[name] = layout
            backup = Path(str(args.config)+'.bak')
            backup.write_bytes(Path(args.config).read_bytes())
            write_json(args.config, all_layouts)
            print('校准已保存。原配置备份: ' + str(backup))
            return
        reader = Reader(layout, args.debug)
        result = reader.scan(frame)
        result['layout'] = name
        write_json(args.output, result)
        print_result(result)
        if args.debug:
            save_image(Path(args.debug)/'regions.png', annotate(frame, layout))
        return
    if args.interval < 0 or args.frames < 0 or args.delay < 0:
        raise ValueError('interval, delay and frames must be nonnegative')
    import mss
    with mss.mss() as capture:
        if args.region:
            left, top, width, height = args.region
            if width <= 0 or height <= 0:
                raise ValueError('Capture dimensions must be positive')
            region = dict(left=left, top=top, width=width, height=height)
        else:
            if not 0 <= args.monitor < len(capture.monitors):
                raise ValueError('Invalid monitor number')
            screen = capture.monitors[args.monitor]
            print(f'{args.delay:g} 秒后截屏，请切换到游戏窗口。随后在截图上框选完整游戏画面。', flush=True)
            time.sleep(args.delay)
            frame = np.asarray(capture.grab(screen))[:,:,:3].copy()
            x, y, w, h = select_region(frame)
            region = dict(left=screen['left']+x, top=screen['top']+y, width=w, height=h)
        reader = None
        stability = Stability(2)
        n = 0
        print('开始识别。Ctrl+C 停止。请保持游戏画面在前台，窗口移动后重新框选。')
        while args.frames == 0 or n < args.frames:
            started = time.perf_counter()
            frame = trim_titlebar(np.asarray(capture.grab(region))[:,:,:3].copy())
            if reader is None:
                name, layout = load_layout(args.config, frame, args.layout)
                reader = Reader(layout)
            result = reader.scan(frame)
            result['layout'] = name
            values = {'pot': result['pot']['value'] if result['pot'] else None,
                      'blinds': (result['blinds']['small'], result['blinds']['big']) if result['blinds'] else None}
            for seat in result['seats']:
                values[seat['seat']+'.stack'] = seat['stack']['value'] if seat['stack'] else None
                values[seat['seat']+'.action'] = seat['action']
                values[seat['seat']+'.bet'] = seat['displayed_bet']['value'] if seat['displayed_bet'] else None
            for group in ('hero_cards', 'board_cards'):
                values.update({group+'.'+str(i): c['card'] for i,c in enumerate(result[group])})
            result['stability'] = {k: stability.observe(k, v) for k, v in values.items()}
            write_json(args.output, result)
            print_result(result)
            n += 1
            time.sleep(max(0., args.interval-(time.perf_counter()-started)))

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n已停止。')
    except Exception as exc:
        print(f'错误: {exc}', file=sys.stderr)
        sys.exit(1)

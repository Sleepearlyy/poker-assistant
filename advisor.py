"""Automatic context + real HU turn/river CFR + explicitly labelled estimate model.

Never describes unknown opponent ranges, future responses or missing OCR as facts.
EV values use chips, measured from the present decision, with folding equal to zero.
"""
import itertools
import json
import math
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from core import SEAT_ORDER, format_chips
from paths import ROOT
from ranges import preflop_top, postflop_top, range_text, text

ENGINE=ROOT/'solver'/'poker-engine.exe'
ORDER=SEAT_ORDER
LABELS={'fold':'弃牌','check':'过牌','call':'跟注','bet':'下注','raise':'加注','all_in':'全下'}
RANKS='23456789TJQKA'
# Share of all starting hands a player opens with, by position (6-max).
OPEN={'枪口':.15,'劫位':.19,'关煞':.25,'按钮':.40,'小盲':.35,'大盲':.15}
# Postflop the preflop history is unknown: assume players who saw the flop hold
# the better 45% of hands, then keep the stronger part for postflop aggression.
POSTFLOP_BASE=.45
POSTFLOP_ACTION={'bet':.45,'raise':.25,'all_in':.3,'call':.7}

def call_engine(request,timeout=18):
    if not ENGINE.exists(): raise RuntimeError('本地求解器文件缺失，请重新安装完整项目。')
    completed=subprocess.run([str(ENGINE)], input=json.dumps(request),text=True,
        encoding='utf-8',stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout,
        cwd=str(ENGINE.parent),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try: result=json.loads(completed.stdout)
    except (ValueError,TypeError): raise RuntimeError('求解器启动失败：'+completed.stderr[-200:])
    if completed.returncode or result.get('error'):raise RuntimeError(result.get('error','求解失败'))
    return result

def ascii_card(card):
    if not card or not card.get('card'):return None
    return card['rank'].replace('10','T')+{'hearts':'h','diamonds':'d','clubs':'c','spades':'s'}[card['suit']]

def combo(cards):
    """Canonical range syntax: higher rank first, e.g. QsJd (the parser rejects JdQs)."""
    return text(*cards)

def bet_value(seat):
    return (seat.get('displayed_bet') or {}).get('value')

def prior(seat,board,dead,bb):
    """Starting range of one opponent from their seat and visible action."""
    act=seat.get('action');role=seat.get('role') or ''
    if not board:
        if act in ('raise','bet'):
            share=OPEN.get(role,.2);note=f'加注 → 前 {share:.0%} 的牌'
        elif act=='all_in':
            deep=((seat.get('stack') or {}).get('value',0)+(bet_value(seat) or 0))>25*bb
            share=.12 if deep else .3;note=f'全下 → 前 {share:.0%} 的牌'
        elif act=='call':
            share=.3 if (bet_value(seat) or 0)>bb*1.01 else .45;note=f'跟注 → 前 {share:.0%} 的牌'
        else:
            share=1.;note='还没主动投入 → 任意牌，按跟注概率缩窄'
        return preflop_top(share,dead),note
    # Sorted strongest first on this board, so narrowing later is just a prefix.
    base=postflop_top(preflop_top(POSTFLOP_BASE,dead),board,1.)
    share=POSTFLOP_ACTION.get(act)
    if share is None:
        return base,f'看到翻牌 → 前 {POSTFLOP_BASE:.0%} 的起手牌'
    return base[:max(1,math.ceil(len(base)*share))],f'{LABELS[act]} → 按当前牌面取较强的 {share:.0%}'

def get_context(snapshot):
    hero=next((s for s in snapshot['seats'] if s['seat']=='bottom'),None)
    if not hero or not hero.get('stack'):raise ValueError('没有读到自己的剩余筹码，请保持游戏无遮挡后再点识别。')
    if hero.get('action')=='fold':raise ValueError('你已弃牌，本手没有可执行的决策。')
    cards=[ascii_card(c) for c in snapshot['hero_cards']]
    if None in cards:raise ValueError('手牌未读全，暂不提供动作建议。')
    board=[];missing=False
    for card in snapshot['board_cards']:
        parsed=ascii_card(card)
        if parsed is None: missing=True
        elif missing:raise ValueError('公牌中间有未识别的位置，请重新识别。')
        else:board.append(parsed)
    if len(board)==0 and any(c.get('status')=='unreadable' for c in snapshot['board_cards']):
        raise ValueError('公牌未读全，请再识别一次。')
    if len(board) not in (0,3,4,5):raise ValueError('公牌尚未完整显示，请再识别一次。')
    if len(set(cards+board))!=len(cards+board):raise ValueError('牌面存在重复读数，暂不计算建议。')
    controls=snapshot.get('controls',{})
    if not controls.get('hero_turn'):raise ValueError('没有看到你的过牌、跟注或全下按钮；轮到你且按钮可见时再点识别。')
    bb=int((snapshot.get('blinds') or {}).get('big') or 1)
    assumptions=[]
    # The center number is what earlier streets collected; chips still in front
    # of players (including folded ones) are on top of it.
    pot=snapshot.get('pot')
    if pot and pot.get('source')=='visible_bets':center=0
    elif pot and pot.get('value',0)>0:center=pot['value']
    elif not board:
        center=0;assumptions.append('翻前中间没有显示底池，按各家面前的下注相加，可能漏掉前注')
    else:raise ValueError('底池金额未读到，暂不计算 EV。')
    to_call=controls.get('to_call');price_source=controls.get('source')
    hero_bet=bet_value(hero) or 0
    bets=[bet_value(s) for s in snapshot['seats'] if s['seat']!='bottom' and bet_value(s)]
    hero_stack=int(hero['stack']['value'])
    if price_source=='all_in_button' and (to_call is None or to_call>hero_stack):
        to_call=hero_stack
    elif to_call is None:
        # This client's call button often shows only "跟注" without a number, so
        # reconstruct the price from the amounts visible on the table.
        if bets:
            to_call=max(0,max(bets)-hero_bet)
            price_source='visible_bet_difference_estimate' if hero_bet else 'visible_bet_max_estimate'
        else:
            to_call=0;price_source='no_visible_bet'
    to_call=max(0,int(to_call))
    level=hero_bet+to_call
    others=[s for s in snapshot['seats'] if s['seat']!='bottom']
    panel_open=bool(snapshot.get('bet_presets'))
    empty=[s for s in others if s['presence']=='empty_or_unreadable' and s.get('action')!='fold']
    # A seat with no nameplate and no action is treated as empty unless the bet
    # panel is open (then it may simply be covered, so keep it as an opponent).
    opponents=[s for s in others if s.get('action')!='fold' and (s['presence']=='occupied' or panel_open)]
    if not opponents:raise ValueError('其他玩家均已弃牌，不需要继续决策。')
    dead=cards+board
    players=[]
    for seat in opponents:
        bet=bet_value(seat)
        if bet is None:
            bet=level if seat.get('action') in ('call','raise','bet','all_in') else 0
        combos,note=prior(seat,board,dead,bb)
        players.append({'seat':seat['seat'],'role':seat.get('role'),'bet':int(bet),
            'stack':int(seat['stack']['value']) if seat.get('stack') else None,
            'all_in':seat.get('action')=='all_in','range':note,'combos':combos})
    dead_money=sum(bet_value(s) or 0 for s in others if s.get('action')=='fold')
    total=center+hero_bet+dead_money+sum(p['bet'] for p in players)
    if total<=0:raise ValueError('底池金额未读到，暂不计算 EV。')
    if total>center:assumptions.append('底池 = 中间数字 + 各家面前的下注（中间数字不含本轮还没收进去的筹码）')
    shove_or_fold=price_source in ('all_in_button','all_in_for_stack') or to_call>hero_stack
    if shove_or_fold:
        to_call=hero_stack;price_source='all_in_for_stack'
        controls['to_call']=to_call;controls['source']='all_in_for_stack'
        # Chips the shover put in beyond what hero can match go back to them.
        cap=hero_bet+hero_stack
        total-=sum(max(0,p['bet']-cap) for p in players)
        for p in players:p['bet']=min(p['bet'],cap)
        assumptions.append('后手不够跟注，只能全下或弃牌；超出你筹码的部分对手会拿回，不算进你能赢的底池')
    if panel_open and empty:
        assumptions.append('下注面板展开时，未读到的座位保守计入在局人数，可能高估人数')
    elif empty:
        assumptions.append(f'未读到名牌和动作的 {len(empty)} 个座位按空位处理；若被动画遮挡可能低估人数')
    if price_source=='visible_bet_difference_estimate':assumptions.append('跟注额来自可见下注求差，可能遗漏被遮挡的下注')
    if price_source=='visible_bet_max_estimate':assumptions.append('跟注额取桌面可见最大下注；自己未显示已投入，可能遗漏被遮挡的下注')
    if price_source=='no_visible_bet':assumptions.append('跟注按钮未显示金额且桌面无可见下注，按 0（过牌成本）计算')
    dealer=(snapshot.get('dealer') or {}).get('seat')
    hero_ip=False
    if dealer in ORDER and len(opponents)==1:
        start=(ORDER.index(dealer)+1)%len(ORDER)
        order=ORDER[start:]+ORDER[:start]
        hero_ip=order.index('bottom')>order.index(opponents[0]['seat'])
    elif len(opponents)==1 and board:assumptions.append('庄家标记未识别，暂按自己无位置求解')
    known=[p['stack'] for p in players if p['stack'] is not None]
    effective=to_call+min([hero_stack-to_call]+known) if not shove_or_fold else hero_stack
    return {'hero':cards,'board':board,'pot':int(total),'center':int(center),'call':int(to_call),
            'hero_bet':int(hero_bet),'level':int(level),'stack':int(effective),'hero_stack':hero_stack,
            'hero_ip':hero_ip,'players':players,'opponents':len(players),'price_source':price_source,
            'bb':bb,'shove_or_fold':shove_or_fold,'assumptions':assumptions,'range_model':'position_strength_v2',
            'ranges_by_seat':{(p['role'] or p['seat']):p['range'] for p in players},
            'all_stacks_known':all(p['stack'] is not None for p in players)}

def action_label(a):
    label=LABELS.get(a['action'],a['action'])
    if a.get('amount'):label+=' '+format_chips(a['amount'])
    return label

def top_part(player,start,end):
    """Hands between two strength quantiles of a player's range (0 = strongest).

    At least 20 combos: tiny ranges of several players can block each other
    so that the sampler cannot deal them all at once.
    """
    combos=player['combos'];lo=math.ceil(len(combos)*start)
    hi=max(lo+20,math.ceil(len(combos)*min(1.,end)))
    if hi>len(combos):lo=max(0,lo-(hi-len(combos)))
    return combos[lo:hi]

def plan_for(context,kind,amount):
    """How the table answers hero putting `amount` more chips in.

    A player facing `need` continues with q=(pot-need)/pot, the share that makes a
    pure bluff break even. Multiway each player continues 1-(1-q)^(1/sqrt(m)): the
    table defends more than one player alone would, but each player less (an UTG
    open then gets through about 40% of the time). The continuing hands are the strongest ones, and
    the top of them re-raise (30% preflop, 20% postflop). Players with nothing to
    add stay in for sure.
    """
    players=context['players'];pot=context['pot'];hero_bet=context['hero_bet']
    new_level=hero_bet+amount;pot_after=pot+amount
    hero_cap=hero_bet+context['hero_stack']
    needs=[max(0,new_level-p['bet']) for p in players]
    needs=[min(n,p['stack']) if p['stack'] is not None else n for n,p in zip(needs,players)]
    facing=[i for i,need in enumerate(needs) if need>0 and not players[i]['all_in']]
    sure=[i for i in range(len(players)) if i not in facing]
    m=max(1,len(facing))
    share={i:1-(1-max(0.,(pot_after-needs[i])/pot_after))**(1/math.sqrt(m)) for i in facing}
    rho=.3 if not context['board'] else .2
    raises={}
    for i in facing:
        p=players[i];cap=p['bet']+p['stack'] if p['stack'] is not None else math.inf
        to=min(3*new_level,cap,hero_cap)
        # A raise worth over a third of what hero has left is played as all-in.
        if to-new_level>(hero_cap-new_level)/3:to=min(cap,hero_cap)
        if to>new_level:
            raises[i]={'p':share[i]*rho,'extra':to-new_level,'final':pot_after+(to-p['bet'])+(to-new_level),
                       'range':(range_text(top_part(p,0,share[i]*rho)),)}
    texts=[range_text(p['combos']) for p in players]
    for i in facing:texts[i]=range_text(top_part(players[i],raises[i]['p'] if i in raises else 0,share[i]))
    cases=[]
    for size in range(min(len(facing),3)+1):
        for chosen in itertools.combinations(facing,size):
            p=math.prod(share[i]-raises.get(i,{'p':0})['p'] if i in chosen else 1-share[i] for i in facing)
            if size==0 or p>=.003:cases.append((p,sure+list(chosen)))
    calm=math.prod(1-r['p'] for r in raises.values())
    scale=sum(p for p,_ in cases) or 1
    weight=sum(r['p'] for r in raises.values()) or 1
    for r in raises.values():r['p']=(1-calm)*r['p']/weight
    return {'action':kind,'amount':amount,'needs':needs,'continue':sum(share.values()),
            'cases':[(p/scale*calm,group,tuple(sorted(texts[i] for i in group))) for p,group in cases],
            'raises':list(raises.values())}

def estimated_actions(context,progress=None):
    """One-decision model: everyone answers once (fold, call or re-raise), then showdown."""
    players=context['players'];pot=context['pot'];cost=context['call']
    hero_bet=context['hero_bet'];level=context['level'];bb=context['bb']
    board=context['board'];stack=context['hero_stack']
    plans=[{'action':'fold','amount':0,'cases':[],'raises':[]}] if cost>0 else []
    if context.get('shove_or_fold'):
        plans.append(plan_for(context,'all_in',cost))
    else:
        plans.append(plan_for(context,'call' if cost else 'check',cost))
        cap=max([p['bet']+(p['stack'] if p['stack'] is not None else 10**12) for p in players
                 if not p['all_in']] or [0])-hero_bet
        top=min(stack,cap)
        if not board:
            if level<=bb:
                limpers=sum(1 for p in players if p['bet']>=bb and p['role']!='大盲')
                targets=[(t+limpers)*bb for t in (2.5,3,4)]
            else:
                targets=[3*level,4*level]
            amounts=[t-hero_bet for t in targets]
            if stack<=25*bb:amounts.append(stack)
        else:
            amounts=list(context.get('bet_presets') or [cost+(pot+cost)*f for f in (1/3,1/2,2/3,1.)])
        minimum=(max(2*level,level+bb) if level else bb)-hero_bet
        if stack<=3*pot:amounts.append(stack)
        for amount in sorted({int(round(min(top,max(minimum,a)))) for a in amounts}):
            if amount<=cost:continue
            plans.append(plan_for(context,'all_in' if amount>=stack else ('raise' if level else 'bet'),amount))
    main=next(p for p in plans if p['action']!='fold')
    main_keys={rs for _,_,rs in main['cases'] if rs}
    unique={rs for p in plans for _,_,rs in p['cases'] if rs}|{r['range'] for p in plans for r in p['raises']}
    if progress:progress(f'正在计算胜率（{len(unique)} 种对手组合）…')
    def run(key):
        request={'mode':'equity','hero':context['hero'],'board':board,'ranges':list(key),
                 'samples':3000 if key in main_keys else 1500}
        return key,call_engine(request,8)
    with ThreadPoolExecutor(8) as pool:
        equity=dict(pool.map(run,unique))
    actions=[];shown=None;error=0.
    for p in plans:
        if p['action']=='fold':
            actions.append({'action':'fold','amount':0,'ev':0.,'frequency':None});continue
        amount=p['amount'];ev=0.;win=0.;seen=0.
        for probability,group,rs in p['cases']:
            if not group:ev+=probability*pot;continue
            result=equity[rs]
            ev+=probability*(result['equity']*(pot+amount+sum(p['needs'][i] for i in group))-amount)
            win+=probability*result['equity'];seen+=probability
            if p is main:error=max(error,result['standard_error'])
        for r in p['raises']:
            # Re-raised: hero folds what is already in, or calls and goes to showdown.
            called=equity[r['range']]['equity']*r['final']-(amount+r['extra'])
            ev+=r['p']*max(-amount,called)
        actions.append({'action':p['action'],'amount':amount,'ev':ev,'frequency':None,
                        'reraised':round(sum(r['p'] for r in p['raises']),3)})
        if p is main:shown=win/seen if seen else 1.
    context['assumptions'].extend([
        '对手范围按位置和可见动作推断（如枪口加注取前 15%，翻后下注取当前牌面较强的部分），不是对手真实手牌',
        '你下注后，对手按"刚好让纯诈唬不赚"的比例继续，继续的是他最强的那部分牌，其中最强的约三成（翻后两成）会再加注；之后直接摊牌，不考虑后续街的下注',
        '筹码 EV；不含抽水或锦标赛 ICM'])
    label='简化模型估算 · 非 GTO'
    if context.get('shove_or_fold'):label='只能全下或弃牌 · '+label
    return {'mode':'estimate','mode_label':label,'actions':actions,'equity':shown,
            'equity_standard_error':error,'converged':False,
            'engine':'local Monte Carlo + strength-ordered response model'}

def analyze(snapshot,progress=None):
    started=time.perf_counter()
    try:context=get_context(snapshot)
    except ValueError as exc:return {'status':'insufficient_data','message':str(exc),'actions':[]}
    context['bet_presets']=snapshot.get('bet_presets',[])
    result=None
    # Flop trees take 10 s+ and stop far from convergence; turn and river solve in under a second.
    if (not context['shove_or_fold'] and context['opponents']==1 and len(context['board'])>=4
            and context['all_stacks_known'] and context['call']<context['pot']):
        if progress:progress('正在本机进行单挑 CFR 求解…')
        base=preflop_top(.45,context['hero']+context['board'])
        opponent=range_text(base);hero_range=opponent+','+combo(context['hero'])
        ranges=[opponent,hero_range] if context['hero_ip'] else [hero_range,opponent]
        try:
            result=call_engine(dict(mode='gto',hero=context['hero'],board=context['board'],
                pot=context['pot'],stack=context['stack'],call=context['call'],hero_ip=context['hero_ip'],ranges=ranges),8)
            result['mode_label']='单挑 GTO 求解' if result['converged'] else '单挑 CFR 近似 · 尚未收敛'
            raise_note='加注仅全下' if result.get('bet_abstraction')=='allin_raise' else '加注 2.5 倍'
            context['assumptions'].append('双方范围都按看到翻牌的前 45% 起手牌；下注 50%/全下、'+raise_note+'；结果仅适用于这个动作树')
        except (RuntimeError,subprocess.TimeoutExpired) as exc:
            reason=str(exc)
            if 'zero reach probability' in reason:
                reason='模型认为对手这个范围几乎不会这样下注（范围估计与实际动作不一致）'
            context['assumptions'].append('单挑求解未完成，已回退到简化模型：'+reason[:140])
            result=None
    if result is None:result=estimated_actions(context,progress)
    for a in result['actions']:
        a['label']=action_label(a)
        a['ev']=round(a['ev'],2)
        a['ev_bb']=round(a['ev']/context['bb'],2)
    key=(lambda a:a.get('frequency') or 0) if result['mode']=='gto' else (lambda a:a['ev'])
    ranked=sorted(result['actions'],key=key,reverse=True)
    recommendation=ranked[0]
    close=None
    if result['mode']=='estimate' and len(ranked)>1:
        # Monte Carlo noise plus model error: a gap under 3% of the pot is a coin flip.
        if ranked[0]['ev']-ranked[1]['ev']<max(.03*context['pot'],context['bb']):close=ranked[1]
    for p in context['players']:p.pop('combos',None)
    result.update(status='ok',context=context,recommendation=recommendation,close=close,
                  required_equity=context['call']/(context['pot']+context['call']) if context['call'] else 0.,
                  elapsed_ms=round((time.perf_counter()-started)*1000),
                  ev_units='chips',ev_reference='当前决策起点，弃牌为0；已投入筹码为沉没成本')
    return result

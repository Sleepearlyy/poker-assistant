use postflop_solver::*;
use rand::{Rng, SeedableRng};
use rand::rngs::SmallRng;
use serde::Deserialize;
use serde_json::{json, Value};
use std::io::{self, Read};
use std::time::{Duration, Instant};

#[derive(Deserialize)]
struct Request {
    mode: String, hero: Vec<String>, board: Vec<String>,
    #[serde(default)] ranges: Vec<String>,
    #[serde(default)] pot: i32,
    #[serde(default)] stack: i32,
    #[serde(default)] call: i32,
    #[serde(default)] hero_ip: bool,
    #[serde(default)] samples: usize,
    #[serde(default)] bet_sizes: Option<String>,
    #[serde(default)] raise_sizes: Option<String>,
}
fn cards(r: &Request) -> Result<(Vec<Card>, Vec<Card>), String> {
    if r.hero.len()!=2 || ![0,3,4,5].contains(&r.board.len()) { return Err("Invalid card counts".into()); }
    let hero: Vec<Card> = r.hero.iter().map(|s|card_from_str(s)).collect::<Result<_,_>>()?;
    let board: Vec<Card> = r.board.iter().map(|s|card_from_str(s)).collect::<Result<_,_>>()?;
    let mut all=hero.clone(); all.extend(&board); all.sort(); all.dedup();
    if all.len()!=hero.len()+board.len() {return Err("Duplicate cards".into());}
    Ok((hero,board))
}
fn range(s: &str) -> Result<Range,String> {
    if s=="random" {Ok(Range::ones())} else {s.parse::<Range>()}
}
fn packed(category:u64, ranks:&[u8])->u64 {
    let mut v=category;
    for i in 0..5 {v=v*15+(*ranks.get(i).unwrap_or(&0) as u64);}
    v
}
fn straight(mask:u16)->u8 {
    for top in (6..=14).rev() { if mask & (31 << (top-4)) == (31 << (top-4)) {return top;} }
    if mask & ((1<<14)|(1<<5)|(1<<4)|(1<<3)|(1<<2)) == ((1<<14)|(1<<5)|(1<<4)|(1<<3)|(1<<2)) {5} else {0}
}
fn strength(cards:&[u8])->u64 {
    let mut counts=[0u8;15]; let mut suits=[0u8;4]; let mut masks=[0u16;4]; let mut mask=0;
    for &c in cards {let rank=c/4+2; let suit=(c%4) as usize;counts[rank as usize]+=1;suits[suit]+=1;masks[suit]|=1<<rank;mask|=1<<rank;}
    let ranks:Vec<u8>=(2..=14).rev().filter(|&i|counts[i as usize]>0).collect();
    let groups=|n:u8| -> Vec<u8> {(2..=14).rev().filter(|&i|counts[i as usize]>=n).collect()};
    if let Some(s)=suits.iter().position(|&n|n>=5) {
        let high=straight(masks[s]); if high>0 {return packed(8,&[high]);}
    }
    let quads=groups(4); if !quads.is_empty() {return packed(7,&[quads[0],*ranks.iter().find(|&&x|x!=quads[0]).unwrap()]);}
    let trips=groups(3); let pairs=groups(2);
    if !trips.is_empty() {if let Some(&p)=pairs.iter().find(|&&x|x!=trips[0]) {return packed(6,&[trips[0],p]);}}
    if let Some(s)=suits.iter().position(|&n|n>=5) {let rs:Vec<u8>=(2..=14).rev().filter(|&i|masks[s]&(1<<i)!=0).collect();return packed(5,&rs[..5]);}
    let high=straight(mask);if high>0{return packed(4,&[high]);}
    if !trips.is_empty() {let mut rs=vec![trips[0]];rs.extend(ranks.iter().filter(|&&x|x!=trips[0]).take(2));return packed(3,&rs);}
    if pairs.len()>=2 {let kicker=*ranks.iter().find(|&&x|x!=pairs[0]&&x!=pairs[1]).unwrap();return packed(2,&[pairs[0],pairs[1],kicker]);}
    if !pairs.is_empty() {let mut rs=vec![pairs[0]];rs.extend(ranks.iter().filter(|&&x|x!=pairs[0]).take(3));return packed(1,&rs);}
    packed(0,&ranks[..5])
}
fn equity(r:&Request)->Result<Value,String>{
    let (hero,board)=cards(r)?;
    if r.ranges.is_empty()||r.ranges.len()>8{return Err("Need 1-8 opponents".into());}
    let dead=hero.iter().chain(board.iter()).fold(0u64,|m,&c|m|1<<c);
    let pools:Vec<_>=r.ranges.iter().map(|s|range(s).map(|v|v.get_hands_weights(dead))).collect::<Result<_,_>>()?;
    if pools.iter().any(|(h,_)|h.is_empty()){return Err("Empty opponent range".into());}
    let n=if r.samples==0{5000}else{r.samples.min(100000)};
    let mut rng=SmallRng::seed_from_u64(0x706f6b6572);let mut sum=0.;let mut squares=0.;let mut done=0;
    for _ in 0..n*200 {
        if done==n{break;}
        let mut hands=Vec::new();let mut used=dead;let mut failed=false;
        for (pool,weights) in &pools {
            let mut selected=None;
            for _ in 0..400 {
                let i=rng.gen_range(0..pool.len());let (a,b)=pool[i];let m=(1u64<<a)|(1u64<<b);
                if rng.gen::<f32>()<weights[i] {
                    // Reject the whole deal on a clash: resampling only this player biases joint ranges.
                    if used&m==0 {selected=Some((a,b));used|=m;}
                    break;
                }
            }
            if let Some(h)=selected{hands.push(h)}else{failed=true;break;}
        }
        if failed{continue;}
        let mut community=board.clone();
        while community.len()<5 {let c=rng.gen_range(0..52u8);if used&(1<<c)==0{used|=1<<c;community.push(c);}}
        let mut hc=community.clone();hc.extend(&hero);let hs=strength(&hc);let mut ties=1.;let mut loses=false;
        for (a,b) in hands {let mut cc=community.clone();cc.extend([a,b]);let s=strength(&cc);if s>hs{loses=true;break;}if s==hs{ties+=1.;}}
        let share=if loses{0.}else{1./ties};sum+=share;squares+=share*share;done+=1;
    }
    if done<n{return Err("Could not sample compatible opponent ranges".into());}
    let mean=sum/done as f64;let error=((squares/done as f64-mean*mean)/done as f64).max(0.).sqrt();
    Ok(json!({"mode":"equity","equity":mean,"standard_error":error,"samples":done}))
}
fn gto(r:&Request)->Result<Value,String>{
    let (hero,board)=cards(r)?;
    if board.len()<3||r.ranges.len()!=2||r.pot<=0||r.stack<=0||r.call<0||r.call>r.stack||r.call>=r.pot{return Err("Invalid heads-up postflop input".into());}
    let start=Instant::now(); let before_pot=r.pot-r.call;
    let bet_base=r.bet_sizes.as_deref().unwrap_or("50%");
    let exact_bet=if r.call>0{format!("{}, {}c, a",bet_base,r.call)}else{format!("{}, a",bet_base)};
    let later_sizes=format!("{}, a",bet_base);
    let state=match board.len(){3=>BoardState::Flop,4=>BoardState::Turn,_=>BoardState::River};
    // Prefer the 2.5x raise abstraction; fall back to all-in raises when the tree is too large.
    let preferred=r.raise_sizes.as_deref().unwrap_or("2.5x");
    let mut chosen=None; let mut last_memory=0u64;
    for raise_base in [preferred,"a"] {
        let sizes=match BetSizeOptions::try_from((exact_bet.as_str(),raise_base)){Ok(v)=>v,Err(e)=>return Err(e.to_string())};
        let later=match BetSizeOptions::try_from((later_sizes.as_str(),raise_base)){Ok(v)=>v,Err(e)=>return Err(e.to_string())};
        let card_config=CardConfig {range:[range(&r.ranges[0])?,range(&r.ranges[1])?],flop:[board[0],board[1],board[2]],turn:*board.get(3).unwrap_or(&NOT_DEALT),river:*board.get(4).unwrap_or(&NOT_DEALT)};
        let tree=ActionTree::new(TreeConfig {initial_state:state,starting_pot:before_pot,effective_stack:r.stack,
            flop_bet_sizes:if board.len()==3{[sizes.clone(),sizes.clone()]}else{[later.clone(),later.clone()]},
            turn_bet_sizes:if board.len()==4{[sizes.clone(),sizes.clone()]}else{[later.clone(),later.clone()]},
            river_bet_sizes:if board.len()==5{[sizes.clone(),sizes]}else{[later.clone(),later]},
            add_allin_threshold:0.,force_allin_threshold:0.,merging_threshold:0.,..Default::default()})?;
        let game=PostFlopGame::with_config(card_config,tree)?;
        let memory=game.memory_usage().1;
        if memory<=512*1024*1024 {chosen=Some((game,memory,raise_base));break;}
        last_memory=memory;
        if raise_base=="a" {break;}
    }
    let (mut game,memory,raise_base)=chosen.ok_or(format!("Tree exceeds 512 MiB limit: {}",last_memory))?;
    game.allocate_memory(true);
    let target=before_pot as f32*0.01;let mut exploit=f32::MAX;let mut iterations=0;
    for i in 0..600 {solve_step(&game,i);iterations=i+1;if (i+1)%20==0{exploit=compute_exploitability(&game);if exploit<=target||start.elapsed()>Duration::from_secs(5){break;}}}
    finalize(&mut game);
    let hero_index=if r.hero_ip{1}else{0};
    let play_check=|g:&mut PostFlopGame|->Result<(),String>{let a=g.available_actions().iter().position(|a|*a==Action::Check).ok_or("No check node")?;g.play(a);Ok(())};
    if (r.call==0&&r.hero_ip)||(r.call>0&&!r.hero_ip){play_check(&mut game)?;}
    if r.call>0 {
        let a=game.available_actions().iter().position(|a|matches!(a,Action::Bet(v)|Action::AllIn(v) if *v==r.call)).ok_or("Observed bet unavailable in tree")?;
        game.play(a);
    }
    if game.current_player()!=hero_index{return Err("Position mismatch".into());}
    game.cache_normalized_weights();
    let hands=game.private_cards(hero_index);let len=hands.len();
    let index=hands.iter().position(|&(a,b)|(a==hero[0]&&b==hero[1])||(a==hero[1]&&b==hero[0])).ok_or("Hero hand excluded from modeled range")?;
    if game.normalized_weights(hero_index)[index]<=0. {return Err("Observed node has zero reach probability".into());}
    let ev=game.expected_values_detail(hero_index);let strategy=game.strategy();
    let actions:Vec<_>=game.available_actions().iter().enumerate().map(|(i,a)|{
        let (kind,size)=match a {Action::Fold=>("fold",0),Action::Check=>("check",0),Action::Call=>("call",r.call),Action::Bet(v)=>("bet",*v),Action::Raise(v)=>("raise",*v),Action::AllIn(v)=>("all_in",*v),_=>("unknown",0)};
        json!({"action":kind,"amount":size,"ev":ev[i*len+index],"frequency":strategy[i*len+index]})
    }).collect();
    Ok(json!({"mode":"gto","actions":actions,"equity":game.equity(hero_index)[index],"exploitability":exploit,"target_exploitability":target,"converged":exploit<=target,"iterations":iterations,"elapsed_ms":start.elapsed().as_millis(),"memory_bytes":memory,"bet_abstraction":if raise_base=="a"{"allin_raise"}else{"2.5x_raise"},"engine":"b-inary/postflop-solver@9d1509f","ev_basis":"incremental_chips_from_current_decision_fold_zero"}))
}
fn main(){
    let _=rayon::ThreadPoolBuilder::new().num_threads(4).build_global();
    let mut input=String::new();io::stdin().read_to_string(&mut input).unwrap();
    let result=(||{let r:Request=serde_json::from_str(&input).map_err(|e|e.to_string())?;match r.mode.as_str(){"gto"=>gto(&r),"equity"=>equity(&r),_=>Err("Unknown mode".into())}})();
    match result {Ok(value)=>println!("{}",value),Err(err)=>{println!("{}",json!({"error":err}));std::process::exit(2);}}
}

#[cfg(test)]
mod tests {
    use super::*;
    fn hand(s:&str)->Vec<u8>{s.split_whitespace().map(|c|card_from_str(c).unwrap()).collect()}
    #[test]fn evaluator(){
        assert!(strength(&hand("Ah Kh Qh Jh Th 2s 3c"))>strength(&hand("Ac Ad Ah As Kd 2s 3c")));
        assert!(strength(&hand("Ac Ad Ah Ks Kd 2s 3c"))>strength(&hand("Ah Kh Qh 9h 6h 2s 3c")));
        assert_eq!(strength(&hand("Ah 2c 3d 4s 5h 9c Td")),packed(4,&[5]));
        assert!(strength(&hand("Ac Ad Ah Ks Kd Kc 3c"))==packed(6,&[14,13]));
    }
    #[test]fn royal_tie(){let r:Request=serde_json::from_value(json!({"mode":"equity","hero":["2c","3d"],"board":["Ah","Kh","Qh","Jh","Th"],"ranges":["random","random"],"samples":1000})).unwrap();let e=equity(&r).unwrap();assert!((e["equity"].as_f64().unwrap()-1./3.).abs()<0.00001);}
}

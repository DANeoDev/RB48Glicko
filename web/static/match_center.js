document.addEventListener('DOMContentLoaded', () => {
    const enterMatch = document.getElementById('enter-match');
    if (!enterMatch) return;

    const parserForm = document.getElementById('mc-form');
    const parserStateKey = 'rb48_match_center_parser_state';
    const matchmakerDetails = document.getElementById('matchmaker-details');
    const matchmakerForm = [...document.querySelectorAll('form')].find(form => form.querySelector('button[name="action"][value="generate"]'));
    const players = window.matchCenterPlayers || {};
    const positionTooltip = 'Positional balance compares how many players on each team can cover GK, DEF, MID and ATT. Lower scores are better; 0 means the teams are perfectly balanced by this evaluation. Goalkeeper imbalance receives an additional heavy penalty.';
    const ratingTooltip = 'Select which Glicko rating type the matchmaker uses when evaluating team strength: Total, BOX, or HF.';

    function playerData(pid) { return players[String(pid)] || players[pid] || {}; }
    function playerAlias(pid) { const p = playerData(pid); return p.aliases?.[0] || `Player ${pid}`; }
    function selectedIds(team) { return [...document.querySelectorAll(`#list-${team} input[name="team_${team}"]`)].map(i => String(i.value)); }
    function updateCount(team) { const e = document.getElementById(`count-${team}`); if (e) e.textContent = `(${selectedIds(team).length})`; }

    function addTeamPlayer(team, pid, alias) {
        pid = String(pid);
        if (selectedIds(team).includes(pid)) return;
        const list = document.getElementById(`list-${team}`); if (!list) return;
        const row = document.createElement('div'); row.className = 'selected-player';
        const name = document.createElement('span'); name.className = 'selected-player-name'; name.textContent = alias || playerAlias(pid);
        const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'remove-player'; remove.textContent = '×';
        remove.addEventListener('click', () => { row.remove(); updateCount(team); });
        const hidden = document.createElement('input'); hidden.type = 'hidden'; hidden.name = `team_${team}`; hidden.value = pid;
        row.append(name, remove, hidden); list.appendChild(row); updateCount(team);
    }

    function restorePlayerPositions() {
        document.querySelectorAll('.players .player').forEach(box => {
            const checkbox = box.querySelector('input[type="checkbox"]');
            const player = playerData(checkbox?.value);
            if (!checkbox || !player) return;
            const positions = Array.isArray(player.positions) ? player.positions.filter(Boolean) : [];
            if (box.querySelector('.player-position')) return;
            const badge = document.createElement('span'); badge.className = 'player-position'; badge.textContent = `(${positions.length ? positions.join(', ') : 'Any'})`;
            badge.style.cssText = 'color:var(--text-muted);font-size:12px;margin-left:6px;'; box.appendChild(badge);
        });
    }

    function setupMiniRatingSelector() {
        if (!matchmakerForm) return;
        const generate = matchmakerForm.querySelector('button[name="action"][value="generate"]'); if (!generate) return;
        const source = [...matchmakerForm.querySelectorAll('select')].find(select => {
            const values = [...select.options].map(o => o.textContent.trim().toLowerCase()); return values.includes('total') && values.includes('box') && values.includes('hf');
        });
        const wrapper = document.createElement('div'); wrapper.className = 'mini-rating-selector'; wrapper.title = ratingTooltip; wrapper.setAttribute('aria-label', ratingTooltip);
        wrapper.style.cssText = 'display:inline-flex;align-items:center;gap:4px;margin-left:4px;vertical-align:middle;';
        const current = source?.value?.toLowerCase() || 'total';
        const hiddenName = source?.name || 'rating_type'; if (source) source.remove();
        [['total','Total'],['box','BOX'],['hf','HF']].forEach(([value,label], index, all) => {
            const button = document.createElement('button'); button.type='button'; button.textContent=label; button.dataset.ratingType=value; button.title=ratingTooltip;
            button.style.cssText='padding:6px 10px;border:1px solid var(--border);background:var(--bg-surface);color:var(--text-main);font:inherit;font-size:12px;font-weight:600;cursor:pointer;';
            if(index===0) button.style.borderRadius='var(--radius) 0 0 var(--radius)'; if(index===all.length-1) button.style.borderRadius='0 var(--radius) var(--radius) 0';
            if(value===current){button.style.background='var(--green-dark)';button.style.borderColor='var(--green-dark)';}
            button.onclick=()=>{wrapper.querySelectorAll('button').forEach(b=>{b.style.background='var(--bg-surface)';b.style.borderColor='var(--border)';});button.style.background='var(--green-dark)';button.style.borderColor='var(--green-dark)';let h=matchmakerForm.querySelector(`input[name="${hiddenName}"]`);if(!h){h=document.createElement('input');h.type='hidden';h.name=hiddenName;matchmakerForm.appendChild(h);}h.value=value;};
            wrapper.appendChild(button);
        });
        generate.insertAdjacentElement('afterend', wrapper);
    }
    setupMiniRatingSelector();

    if (parserForm && matchmakerForm && parserForm.querySelector('[name="parsed_kind"]')) {
        matchmakerForm.addEventListener('submit', () => {
            const get = n => parserForm.querySelector(`[name="${n}"]`)?.value || '';
            const parsedPlayers = [...parserForm.querySelectorAll('[name="parsed_player"]')].map(x=>x.value);
            sessionStorage.setItem(parserStateKey, JSON.stringify({kind:get('parsed_kind'),date:get('parsed_match_date'),teamA:get('parsed_team_a'),teamB:get('parsed_team_b'),goalsA:get('parsed_goals_a'),goalsB:get('parsed_goals_b'),players:parsedPlayers}));
        });
    }

    const generated = document.getElementById('generated-teams');
    if (generated && matchmakerDetails) {
        matchmakerDetails.open = true;
        const suggested = generated.closest('.card'); if (suggested) setTimeout(()=>suggested.scrollIntoView({behavior:'smooth',block:'center'}),80);
    }

    const saved = sessionStorage.getItem(parserStateKey);
    if (saved) {
        try {
            const state=JSON.parse(saved); const date=document.getElementById('match-date'); const goalsA=enterMatch.querySelector('[name="goals_a"]'); const goalsB=enterMatch.querySelector('[name="goals_b"]');
            if(date&&state.date)date.value=state.date; if(goalsA&&state.goalsA!=='')goalsA.value=state.goalsA; if(goalsB&&state.goalsB!=='')goalsB.value=state.goalsB;
            const restoreTeam=(key,team)=>String(state[key]||'').split('||').filter(Boolean).forEach(raw=>{const wanted=raw.trim().toLowerCase();const box=[...document.querySelectorAll('.player')].find(b=>b.querySelector('.player-name')?.textContent?.trim().toLowerCase()===wanted);const cb=box?.querySelector('input[type="checkbox"]');if(cb)addTeamPlayer(team,cb.value,playerAlias(cb.value));});
            restoreTeam('teamA','a'); restoreTeam('teamB','b');
        } catch (_) {} finally { sessionStorage.removeItem(parserStateKey); }
    }

    const conflictList=document.querySelector('.conflict-list');
    if(conflictList){conflictList.style.display='flex';conflictList.style.flexWrap='wrap';conflictList.style.gap='8px 14px';conflictList.style.alignItems='center';conflictList.querySelector(':scope > strong')?.style.setProperty('width','100%');conflictList.querySelectorAll('.conflict-row').forEach(r=>{r.style.display='inline-flex';r.style.margin='0';});}

    const aliasSubmit=document.getElementById('alias-submit'); const aliasId=document.getElementById('alias-id'); const addName=document.getElementById('add-name');
    let aliasConfirmed=false, aliasModal=null;
    if(aliasSubmit){
        const ensure=()=>{if(aliasModal)return aliasModal;aliasModal=document.createElement('div');aliasModal.className='modal-bg';aliasModal.innerHTML='<div class="modal"><h3>Confirm alias</h3><p id="alias-confirm-text"></p><div class="modal-actions"><button type="button" class="primary" id="alias-confirm">Add alias</button><button type="button" class="secondary" id="alias-confirm-cancel">Cancel</button></div></div>';document.body.appendChild(aliasModal);aliasModal.querySelector('#alias-confirm-cancel').onclick=()=>aliasModal.style.display='none';aliasModal.querySelector('#alias-confirm').onclick=()=>{aliasModal.style.display='none';aliasConfirmed=true;aliasSubmit.click();aliasConfirmed=false;};return aliasModal;};
        document.addEventListener('click',event=>{if(event.target!==aliasSubmit||aliasConfirmed)return;event.preventDefault();event.stopImmediatePropagation();const modal=ensure();modal.querySelector('#alias-confirm-text').textContent=`Add alias "${addName?.textContent?.trim()||'this name'}" to "${aliasId?.selectedOptions?.[0]?.textContent?.trim()||'the selected player'}"?`;modal.style.display='flex';},true);
    }

    if(matchmakerForm&&generated&&!matchmakerForm.querySelector('[data-reroll]')){
        const reroll=document.createElement('button');reroll.type='submit';reroll.name='action';reroll.value='reroll';reroll.textContent='Reroll';reroll.className='secondary';reroll.dataset.reroll='true';reroll.title='Generate another team composition from the same selected players.';
        const seed=document.createElement('input');seed.type='hidden';seed.name='seed';seed.value=String(Date.now());matchmakerForm.appendChild(seed);reroll.onclick=()=>seed.value=String(Date.now()+Math.floor(Math.random()*100000));matchmakerForm.querySelector('.actions')?.appendChild(reroll);
    }

    if(generated){
        let teams=null;try{teams=JSON.parse(generated.textContent);}catch(_){ }
        if(teams?.a?.length&&teams?.b?.length){
            const suggested=generated.closest('.card');
            if(suggested&&!suggested.querySelector('.team-quality')){
                const quality=document.createElement('div');quality.className='notice team-quality';quality.textContent='Loading team details…';suggested.querySelector('.actions')?.before(quality);
                const params=new URLSearchParams();teams.a.forEach(id=>params.append('team_a',id));teams.b.forEach(id=>params.append('team_b',id));
                fetch(`/match-center/team-details?${params.toString()}`).then(r=>r.ok?r.json():Promise.reject()).then(d=>{quality.innerHTML=`<strong>Team rating:</strong> ${d.rating_a} (RD ${d.rd_a}) vs ${d.rating_b} (RD ${d.rd_b}) · <strong>Rating difference:</strong> ${d.rating_difference}<br><strong title="${positionTooltip}">Positional balance:</strong> ${d.position_penalty===0?'balanced':`penalty ${d.position_penalty}`}<br><span class="muted">Team A: ${Object.values(d.positions_a).join(', ')} · Team B: ${Object.values(d.positions_b).join(', ')}</span>`;});
            }
        }
    }

    const resultSummary=document.querySelector('.result-summary'); if(resultSummary){const label=[...resultSummary.querySelectorAll('strong')].find(e=>e.textContent.includes('Positional balance evaluation'));if(label){label.title=positionTooltip;label.style.cursor='help';}}
    restorePlayerPositions();

    const useTeams=[...document.querySelectorAll('a.primary')].find(a=>a.textContent.trim()==='Use these teams in Enter a Match');
    if(generated&&useTeams){
        let teams;try{teams=JSON.parse(generated.textContent);}catch(_){teams=null;} if(teams)useTeams.addEventListener('click',event=>{event.preventDefault();const current=enterMatch.querySelectorAll('input[name="team_a"],input[name="team_b"]');const ga=enterMatch.querySelector('[name="goals_a"]')?.value||'0';const gb=enterMatch.querySelector('[name="goals_b"]')?.value||'0';const apply=()=>{['a','b'].forEach(team=>{document.getElementById(`list-${team}`)?.querySelectorAll('.selected-player').forEach(r=>r.remove());(teams[team]||[]).forEach(id=>addTeamPlayer(team,id));});enterMatch.scrollIntoView({behavior:'smooth'});};if(current.length||ga!=='0'||gb!=='0'){if(confirm('Are you certain you want to overwrite the current configuration?'))apply();}else apply();});
    }
});
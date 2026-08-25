document.addEventListener('DOMContentLoaded', () => {
    const enterMatch = document.getElementById('enter-match');
    if (!enterMatch) return;

    const parserForm = document.getElementById('mc-form');
    const parserStateKey = 'rb48_match_center_parser_state';
    const matchmakerDetails = document.getElementById('matchmaker-details');
    const matchmakerForm = [...document.querySelectorAll('form')].find(form => form.querySelector('button[name="action"][value="generate"]'));

    if (parserForm && matchmakerForm && parserForm.querySelector('[name="parsed_kind"]')) {
        matchmakerForm.addEventListener('submit', () => {
            const get = name => parserForm.querySelector(`[name="${name}"]`)?.value || '';
            const players = [...parserForm.querySelectorAll('[name="parsed_player"]')].map(x => x.value);
            sessionStorage.setItem(parserStateKey, JSON.stringify({kind:get('parsed_kind'),date:get('parsed_match_date'),teamA:get('parsed_team_a'),teamB:get('parsed_team_b'),goalsA:get('parsed_goals_a'),goalsB:get('parsed_goals_b'),players}));
        });
    }

    const generated = document.getElementById('generated-teams');
    if (generated && matchmakerDetails) {
        matchmakerDetails.open = true;
        const suggested = generated.closest('.card');
        if (suggested) setTimeout(() => suggested.scrollIntoView({behavior:'smooth', block:'center'}), 80);
    }

    const saved = sessionStorage.getItem(parserStateKey);
    if (saved) {
        try {
            const state = JSON.parse(saved);
            const date = document.getElementById('match-date');
            const goalsA = enterMatch.querySelector('[name="goals_a"]');
            const goalsB = enterMatch.querySelector('[name="goals_b"]');
            if (date && state.date) date.value = state.date;
            if (goalsA && state.goalsA !== '') goalsA.value = state.goalsA;
            if (goalsB && state.goalsB !== '') goalsB.value = state.goalsB;
            const restoreTeam = (key, team) => {
                String(state[key] || '').split('||').filter(Boolean).forEach(rawName => {
                    const wanted = rawName.trim().toLowerCase();
                    const player = [...document.querySelectorAll('.player')].find(box => box.querySelector('span')?.textContent?.trim().toLowerCase() === wanted);
                    const checkbox = player?.querySelector('input[type="checkbox"]');
                    if (checkbox && typeof window.addPlayer === 'function') window.addPlayer(team, checkbox.value, player.querySelector('span').textContent.trim());
                });
            };
            restoreTeam('teamA','a'); restoreTeam('teamB','b');
        } catch (_) {} finally { sessionStorage.removeItem(parserStateKey); }
    }

    const conflictList = document.querySelector('.conflict-list');
    if (conflictList) {
        conflictList.style.display='flex'; conflictList.style.flexWrap='wrap'; conflictList.style.gap='8px 14px'; conflictList.style.alignItems='center';
        conflictList.title='Names do not imply identity. Make sure the listed player is the person already in the database, or edit the name details and add a new player.';
        conflictList.setAttribute('aria-label','Possible name conflicts. Names do not imply identity.');
        const title=conflictList.querySelector(':scope > strong');
        if(title){title.style.width='100%';title.style.marginBottom='2px';}
        conflictList.querySelectorAll('.conflict-row').forEach(row=>{row.style.display='inline-flex';row.style.margin='0';});
        conflictList.querySelectorAll('.conflict-btn').forEach(button=>button.title='Names do not imply identity. Click to confirm or edit this player.');
        conflictList.querySelectorAll('.conflict-row .muted').forEach(status=>status.style.display='none');
    }

    const aliasSubmit=document.getElementById('alias-submit');
    const aliasId=document.getElementById('alias-id');
    const addName=document.getElementById('add-name');
    let aliasConfirmed=false, aliasModal=null;
    if(aliasSubmit){
        aliasSubmit.title='If this is a common name, it is better to select the player manually instead of assigning a possibly overloaded alias.';
        const ensureAliasModal=()=>{
            if(aliasModal)return aliasModal;
            aliasModal=document.createElement('div'); aliasModal.className='modal-bg';
            aliasModal.innerHTML='<div class="modal"><h3>Confirm alias</h3><p id="alias-confirm-text"></p><div class="modal-actions"><button type="button" class="primary" id="alias-confirm">Add alias</button><button type="button" class="secondary" id="alias-confirm-cancel">Cancel</button></div></div>';
            document.body.appendChild(aliasModal);
            aliasModal.querySelector('#alias-confirm-cancel').onclick=()=>aliasModal.style.display='none';
            aliasModal.querySelector('#alias-confirm').onclick=()=>{aliasModal.style.display='none';aliasConfirmed=true;aliasSubmit.click();aliasConfirmed=false;};
            return aliasModal;
        };
        document.addEventListener('click',event=>{
            if(event.target!==aliasSubmit||aliasConfirmed)return;
            event.preventDefault();event.stopImmediatePropagation();
            const modal=ensureAliasModal();
            const alias=addName?.textContent?.trim()||'this name';
            const selected=aliasId?.selectedOptions?.[0]?.textContent?.trim()||'the selected player';
            modal.querySelector('#alias-confirm-text').textContent=`Add alias "${alias}" to "${selected}"?`;
            modal.style.display='flex';
        },true);
    }

    if(matchmakerForm&&generated&&!matchmakerForm.querySelector('[data-reroll]')){
        const reroll=document.createElement('button'); reroll.type='submit'; reroll.name='action'; reroll.value='reroll'; reroll.textContent='Reroll'; reroll.className='secondary'; reroll.dataset.reroll='true'; reroll.title='Generate another team composition from the same selected players.';
        const seed=document.createElement('input'); seed.type='hidden'; seed.name='seed'; seed.value=String(Date.now());
        matchmakerForm.appendChild(seed); reroll.addEventListener('click',()=>seed.value=String(Date.now()+Math.floor(Math.random()*100000)));
        matchmakerForm.querySelector('.actions')?.appendChild(reroll);
    }

    if(generated){
        let teams=null; try{teams=JSON.parse(generated.textContent);}catch(_){ }
        if(teams?.a?.length&&teams?.b?.length){
            const suggested=generated.closest('.card');
            if(suggested&&!suggested.querySelector('.team-quality')){
                const quality=document.createElement('div'); quality.className='notice team-quality'; quality.textContent='Loading team details…'; suggested.querySelector('.actions')?.before(quality);
                const params=new URLSearchParams(); teams.a.forEach(id=>params.append('team_a',id)); teams.b.forEach(id=>params.append('team_b',id));
                fetch(`/match-center/team-details?${params.toString()}`).then(r=>r.ok?r.json():Promise.reject()).then(d=>{
                    quality.innerHTML=`<strong>Team rating:</strong> ${d.rating_a} (RD ${d.rd_a}) vs ${d.rating_b} (RD ${d.rd_b}) · <strong>Rating difference:</strong> ${d.rating_difference}<br><strong>Positional balance:</strong> ${d.position_penalty===0?'balanced':`penalty ${d.position_penalty}`}<br><span class="muted">Team A: ${Object.values(d.positions_a).join(', ')} · Team B: ${Object.values(d.positions_b).join(', ')}</span>`;
                }).catch(()=>quality.textContent='Team details could not be loaded.');
            }
        }
    }

    const useTeams=[...document.querySelectorAll('a.primary')].find(a=>a.textContent.trim()==='Use these teams in Enter a Match');
    if(generated&&useTeams){
        let teams; try{teams=JSON.parse(generated.textContent);}catch(_){teams=null;} if(!teams)return;
        useTeams.addEventListener('click',event=>{
            event.preventDefault();
            const currentTeams=document.querySelectorAll('#enter-match input[name="team_a"], #enter-match input[name="team_b"]');
            const currentGoalsA=enterMatch.querySelector('[name="goals_a"]')?.value||'0'; const currentGoalsB=enterMatch.querySelector('[name="goals_b"]')?.value||'0';
            const hasCurrentConfiguration=currentTeams.length>0||currentGoalsA!=='0'||currentGoalsB!=='0';
            const apply=()=>{
                ['a','b'].forEach(team=>{
                    const list=document.getElementById(`list-${team}`); if(!list)return;
                    list.querySelectorAll('.selected-player').forEach(row=>row.remove());
                    (teams[team]||[]).forEach(id=>{const player=document.querySelector(`.player input[value="${id}"]`)?.closest('.player');const name=player?.querySelector('span')?.textContent?.trim()||`Player ${id}`;if(typeof window.addPlayer==='function')window.addPlayer(team,id,name);});
                });
                enterMatch.scrollIntoView({behavior:'smooth'});
            };
            if(hasCurrentConfiguration){if(confirm('Are you certain you want to overwrite the current configuration?'))apply();}else apply();
        });
    }
});

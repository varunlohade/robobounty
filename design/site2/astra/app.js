'use strict';
const $ = (query, root = document) => root.querySelector(query);
const $$ = (query, root = document) => [...root.querySelectorAll(query)];
let toastTimer;
function notify(message) {
  const toast = $('.toast');
  toast.textContent = message;
  toast.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 4500);
}
function openDialog(title, body, note) {
  const dialog = document.createElement('dialog');
  const head = document.createElement('div');
  head.className = 'dialog-head';
  const heading = document.createElement('h2');
  heading.textContent = title;
  const close = document.createElement('button');
  close.className = 'button';
  close.textContent = 'Close';
  close.addEventListener('click', () => dialog.close());
  head.append(heading, close);
  dialog.append(head, body);
  if (note) {
    const caption = document.createElement('p');
    caption.className = 'dialog-note';
    caption.textContent = note;
    dialog.append(caption);
  }
  document.body.append(dialog);
  dialog.addEventListener('close', () => dialog.remove());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.showModal();
}
$$('[data-replay]').forEach(button => button.addEventListener('click', () => {
  const frame = document.createElement('img');
  frame.src = `assets/${button.dataset.replay}`;
  frame.alt = 'Full supplied frame from the recorded simulation';
  openDialog('Recorded run · Frame preview', frame, 'Simulated. Hand-built physics. This preview contains a still frame; playback is available in the simulator.');
}));
$('#verify')?.addEventListener('click', event => {
  const button = event.currentTarget;
  button.textContent = 'Waiting for World ID…';
  button.disabled = true;
  $('#verify-state').setAttribute('role', 'status');
  $('#verify-state').innerHTML = '<span class="verify-ring"></span><div>Verify in World ID<div class="small muted">Preview only · authentication is not connected</div></div>';
  notify('Verification preview. No authentication request was sent.');
});
const robotData = {
  window: {
    image: 'lab-3.png', title: 'dubai_tower.world', environment: 'Glass tower', campaign: '33 worlds run',
    description: 'Change the glass, weather and tower geometry. Watch where the controller holds, slips or loses contact.',
    caption: 'Wet glass + strong wind', state: 'Safe hold'
  },
  inspection: {
    image: 'inspection-plant-t17.png', title: 'inspection_plant.world', environment: 'Industrial plant', campaign: '34 worlds run',
    description: 'Change the route, walkway and obstacles. Inspect where the upstream policy clears a boundary or loses its footing.',
    caption: 'Default plant route', state: 'Passed'
  }
};
$$('[data-robot]').forEach(button => {
  button.setAttribute('aria-pressed', String(button.classList.contains('active')));
  button.addEventListener('click', () => {
    $$('[data-robot]').forEach(item => { item.classList.remove('active'); item.setAttribute('aria-pressed', 'false'); });
    button.classList.add('active');
    button.setAttribute('aria-pressed', 'true');
    const key = button.dataset.robot;
    const data = robotData[key];
    $('#robot-description').textContent = data.description;
    $('#environment').textContent = data.environment;
    $('#campaign').textContent = data.campaign;
    $('#world-label').textContent = data.title;
    const scene = $('#robot-scene .scene');
    scene.classList.toggle('inspection', key === 'inspection');
    $('img', scene).src = `assets/${data.image}`;
    $('img', scene).alt = `Recorded simulation: ${data.environment}`;
    $('.scene-label', scene).textContent = `Simulated / ${key === 'window' ? 'Window cleaning' : 'Plant inspection'}`;
    $('.replay-bar .small').textContent = data.caption;
    $('.replay-bar [data-replay]').dataset.replay = data.image;
    $('.preview-tag').textContent = data.state;
    $('.preview-tag').style.color = key === 'inspection' ? 'var(--green)' : 'var(--amber)';
    $('#launch-lab').href = key === 'window' ? 'lab.html' : 'lab.html?robot=inspection';
  });
});
$$('[data-filter-group] button').forEach(button => {
  button.setAttribute('aria-pressed', String(button.classList.contains('active')));
  button.addEventListener('click', () => {
    $$('[data-filter-group] button').forEach(item => {item.classList.remove('active'); item.setAttribute('aria-pressed', 'false');});
    button.classList.add('active');
    button.setAttribute('aria-pressed', 'true');
    $$('.bounty-row').forEach(row => {row.hidden = button.dataset.filter !== 'all' && row.dataset.status !== button.dataset.filter;});
    const visible = $$('.bounty-row').filter(row => !row.hidden);
    if (visible.length && !visible.some(row => row.classList.contains('active'))) visible[0].click();
  });
});
const bountyDetails = {
  '1200': {id:'CL-014',description:'Keep contact while crossing a wet section of glass. The fix must preserve safe holds outside the operating limit.', world:'wet_glass.world', failure:'Suction loss at the surface boundary.', image:'weather-rain.png'},
  '800': {id:'CL-015',description:'Recover contact at a panel boundary. The controller must return to a safe state without compromising the tether.', world:'panel_edge.world', failure:'Loss of contact at a panel edge.', image:'build-part-ac_unit.png'},
  '1500': {id:'CL-016',description:'Clear the low-pipe obstacle on the inspection route. The controller must remain stable through the remaining waypoints.', world:'low_pipe_0.world', failure:'The robot fell near the low pipe.', image:'grid-detail.png'}
};
$$('.bounty-row').forEach(row => {
  row.setAttribute('aria-pressed', String(row.classList.contains('active')));
  row.addEventListener('click', () => {
    $$('.bounty-row').forEach(item => {item.classList.remove('active'); item.setAttribute('aria-pressed','false');});
    row.classList.add('active');
    row.setAttribute('aria-pressed','true');
    const data = bountyDetails[row.dataset.reward];
    $('#bounty-title').textContent = row.dataset.title;
    $('#bounty-id').textContent = data.id;
    $('#bounty-description').textContent = data.description;
    $('#bounty-world').textContent = data.world;
    $('#bounty-failure').textContent = data.failure;
    $('.failure-preview img').src = `assets/${data.image}`;
    $('.failure-preview img').alt = `Supplied simulation frame for ${row.dataset.title}`;
    $('.failure-preview [data-replay]').dataset.replay = data.image;
  });
});
let sortDescending = false;
$('#sort-bounties')?.addEventListener('click', () => {
  sortDescending = !sortDescending;
  const rows = $$('.bounty-row').sort((a,b) => sortDescending ? Number(b.dataset.reward)-Number(a.dataset.reward) : Number(a.dataset.reward)-Number(b.dataset.reward));
  const list = $('#bounty-list');
  rows.forEach(row => list.insertBefore(row, $('.list-note', list)));
  $('#sort-bounties').setAttribute('aria-label', `Reward sorted ${sortDescending ? 'highest' : 'lowest'} first`);
  notify(`Sample rewards sorted ${sortDescending ? 'highest' : 'lowest'} first.`);
});
$('#requirements')?.addEventListener('click', () => {
  const content = document.createElement('div');
  content.className = 'requirements-copy';
  content.innerHTML = '<p>Sample validation requirements</p><ol><li>Attach a controller patch and describe the change.</li><li>Pass the public failing worlds without regressing safe holds.</li><li>Pass the private validator. Hidden world definitions remain hidden.</li><li>Review the validation result before any ledger update.</li></ol><p>No patch is attached. Submission and payment are not connected.</p>';
  openDialog('Validation requirements', content);
});
$('#failure-search')?.addEventListener('input', event => {
  const query = event.target.value.trim().toLowerCase();
  const rows = $$('#failure-rows tr');
  rows.forEach(row => {row.hidden = !row.dataset.search.includes(query);});
  const count = rows.filter(row => !row.hidden).length;
  $('#failure-count').textContent = count ? `${count} sample record${count===1?'':'s'}` : 'No matching failures';
});
document.addEventListener('keydown', event => {
  if (event.key === '/' && $('#failure-search') && !['INPUT','TEXTAREA'].includes(document.activeElement.tagName) && !$('dialog[open]')) {
    event.preventDefault();
    $('#failure-search').focus();
  }
});
let navigationPrefix = 0;
document.addEventListener('keydown', event => {
  if (event.metaKey || event.ctrlKey || event.altKey || ['INPUT','TEXTAREA'].includes(document.activeElement.tagName) || $('dialog[open]')) return;
  if (event.key.toLowerCase() === 'g') navigationPrefix = Date.now();
  else if (event.key.toLowerCase() === 'l' && Date.now() - navigationPrefix < 1000) window.location.href = 'crashlab.html';
  else navigationPrefix = 0;
});

const $ = (id) => document.getElementById(id);
let selectedIncidentId = null;
let refreshBusy = false;

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function fmtTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString([], {month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
}
function fmtShort(value) {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
}
function fmtBytes(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  let n=Number(value), unit='B';
  for (const u of ['B','KB','MB','GB','TB']) { unit=u; if (n<1024 || u==='TB') break; n/=1024; }
  return `${n.toFixed(1)} ${unit}`;
}
function fmtRate(value) { return value == null ? '—' : `${fmtBytes(value)}/s`; }
function niceKind(value) { return String(value || 'finding').replaceAll('_',' ').replace(/\b\w/g, x=>x.toUpperCase()); }
function toast(message) {
  const node=$('toast'); node.textContent=message; node.classList.add('show');
  window.clearTimeout(toast.timer); toast.timer=window.setTimeout(()=>node.classList.remove('show'),3000);
}
async function api(path, options={}) {
  const response=await fetch(path,options);
  if(!response.ok){let message=`${response.status} ${response.statusText}`;try{const data=await response.json();message=data.detail||message}catch(_){}throw new Error(message)}
  return response.json();
}
function setBar(id,value) {
  const node=$(id); const n=value==null?0:Math.max(0,Math.min(100,Number(value)));
  node.style.width=`${n}%`;
  node.style.background=n>=90?'linear-gradient(90deg,#d66b72,#e18b83)':n>=80?'linear-gradient(90deg,#d9a044,#edc06d)':'linear-gradient(90deg,#5e9af1,#87b5f2)';
}
function renderConnection(data) {
  const status=data.collector||{}, latest=data.latest;
  const pill=$('connection-pill'), dbState=$('db-state');
  const connected=!!status.connected;
  pill.classList.toggle('connected',connected); pill.classList.toggle('error',!connected&&!!status.last_error);
  $('connection-label').textContent=connected?'PostgreSQL connected':(status.last_error?'Connection issue':'Connecting to PostgreSQL');
  $('hero-last-capture').textContent=status.last_success_at?`Last captured ${fmtShort(status.last_success_at)}`:'Waiting for first capture';
  $('collector-interval').textContent=`${data.settings.collect_interval_seconds} sec`;
  $('query-capture').textContent=data.settings.capture_query_text?'Enabled':'Disabled';
  dbState.className=`db-state ${connected?'connected':status.last_error?'error':''}`;
  const evidenceStatus=$('evidence-collector-status');
  if(evidenceStatus){evidenceStatus.innerHTML=`<i></i> ${connected?'COLLECTING':status.last_error?'COLLECTOR ISSUE':'CONNECTING'}`;evidenceStatus.style.color=connected?'#62997d':status.last_error?'#bb5964':'#9aa6b5';}
  dbState.querySelector('span').textContent=connected?'CONNECTED':status.last_error?'ATTENTION':'CONNECTING';
  if(!latest){
    $('db-name').textContent=status.last_error?'PostgreSQL connection not ready':'Waiting for first snapshot';
    $('db-version').textContent=status.last_error||'The collector will attempt a read-only connection automatically.';
    $('db-visibility').textContent='Unavailable';
      return;
  }
  $('db-name').textContent=`${latest.db_name} · ${latest.visibility?.connected_user||'monitoring role'}`;
  $('db-version').textContent=`PostgreSQL ${latest.server_version} · ${latest.is_in_recovery?'Standby / recovery':'Primary or standalone'} · ${fmtBytes(latest.database_size_bytes)}`;
  $('db-visibility').textContent=latest.visibility?.has_pg_read_all_stats?'Full statistics':'Limited';
  $('snapshot-time').textContent=`CAPTURED ${fmtTime(latest.captured_at).toUpperCase()}`;
}
function renderMetrics(latest,counts) {
  if(!latest)return;
  const max=Number(latest.max_connections||0), used=Number(latest.total_client_backends||0), pct=max?used/max*100:0;
  $('metric-connections').textContent=`${used} / ${max}`;
  $('metric-connection-pct').textContent=`${pct.toFixed(1)}% utilized`;
  setBar('connection-progress',pct);
  $('connection-footnote').textContent=pct>=95?'Near configured max_connections capacity.':pct>=80?'Connection utilization is elevated.':'Visible client backend utilization.';
  $('metric-active').textContent=latest.active_sessions??'—';
  $('active-subtitle').textContent=`${latest.idle_sessions??0} idle sessions`;
  $('metric-locks').textContent=latest.lock_waiters??'—';
  $('lock-subtitle').textContent=latest.lock_waiters?'Lock wait observed':'No lock wait in this sample';
  $('metric-open-incidents').textContent=counts?.open_incidents??0;
  $('incident-subtitle').textContent=counts?.open_incidents?`${counts.open_incidents} active finding(s)`:'No active findings';
}
function lineChart(points) {
  const svg=$('trend-chart');
  if(!points||points.length<2){svg.innerHTML='<text x="24" y="120" class="chart-empty">Collecting history… at least two successful samples are needed.</text>';$('chart-range').textContent=`${points?.length||0} sample(s) retained`;return}
  const W=820,H=250,L=42,R=16,T=18,B=30,iw=W-L-R,ih=H-T-B;
  const series=[...points.map(p=>Number(p.total_client_backends||0)),...points.map(p=>Number(p.active_sessions||0))];
  const max=Math.max(5,...series), x=i=>L+i/(points.length-1)*iw, y=v=>T+ih-(v/max)*ih;
  const path=key=>points.map((p,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(p[key]||0).toFixed(1)}`).join(' ');
  const area=`${path('total_client_backends')} L${x(points.length-1)},${T+ih} L${L},${T+ih} Z`;
  const grid=[0,.25,.5,.75,1].map(f=>{const yy=T+ih*f;return `<line class="gridline" x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}"/><text class="axis-label" x="5" y="${yy+3}">${Math.round(max*(1-f))}</text>`}).join('');
  const ix=[0,Math.floor((points.length-1)/2),points.length-1];
  const labels=ix.map(i=>`<text class="axis-label" text-anchor="${i===0?'start':i===points.length-1?'end':'middle'}" x="${x(i)}" y="${H-7}">${fmtShort(points[i].captured_at)}</text>`).join('');
  svg.innerHTML=`<defs><linearGradient id="areaBlue" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#4e8bf0"/><stop offset="100%" stop-color="#4e8bf0" stop-opacity="0"/></linearGradient></defs>${grid}${labels}<path class="area-connections" d="${area}"/><path class="line-connections" d="${path('total_client_backends')}"/><path class="line-active" d="${path('active_sessions')}"/>`;
  $('chart-range').textContent=`${points.length} samples · ${fmtTime(points[0].captured_at)} → ${fmtTime(points.at(-1).captured_at)}`;
}
function renderHost(host) {
  if(!host?.available){$('host-live').textContent='UNAVAILABLE';$('host-live').classList.remove('available');$('host-name').textContent='Host telemetry unavailable';$('host-platform').textContent=host?.error||'Install project requirements to enable host metrics.';return}
  $('host-live').textContent='CAPTURING';$('host-live').classList.add('available');
  $('host-name').textContent=host.hostname||'Collector host';$('host-platform').textContent=host.platform||'Collector machine';
  const values=[['cpu_percent','host-cpu-value','host-cpu-bar','host-cpu-sub'],['memory_percent','host-memory-value','host-memory-bar','host-memory-sub'],['disk_percent','host-disk-value','host-disk-bar','host-disk-sub']];
  for(const [key,valueId,barId,subId] of values){const v=host[key];$(valueId).textContent=v==null?'Warming up':`${Number(v).toFixed(1)}%`;setBar(barId,v);}
  $('host-memory-sub').textContent=host.memory_used_bytes!=null?`${fmtBytes(host.memory_used_bytes)} of ${fmtBytes(host.memory_total_bytes)}`:'Collector host memory';
  $('host-disk-sub').textContent=host.disk_used_bytes!=null?`${fmtBytes(host.disk_used_bytes)} of ${fmtBytes(host.disk_total_bytes)} · ${host.disk_path||'root volume'}`:'Collector host root volume';
  $('host-cpu-sub').textContent='Sampled on the machine running this collector.';$('host-disk-sub').textContent=`${host.disk_path||'Root volume'} · read ${fmtRate(host.disk_read_bytes_per_sec)} · write ${fmtRate(host.disk_write_bytes_per_sec)}`;
}
function renderApplications(items) {
  const body=$('application-rows');$('application-count').textContent=`${items?.length||0} APPS`;
  if(!items?.length){body.innerHTML='<tr><td colspan="4" class="empty-state">No application sessions are visible in the latest sample.</td></tr>';return}
  body.innerHTML=items.map(app=>{
    const name=app.application_name||'(unnamed client)',sessions=Number(app.total_sessions||0),active=Number(app.active_sessions||0),locks=Number(app.lock_waiters||0),share=sessions?Math.min(100,active/sessions*100):0;
    return `<tr><td><span class="app-name">${esc(name)}</span><span class="app-secondary">max query age ${esc(app.max_query_age_seconds??'—')}s</span></td><td><strong>${sessions}</strong><div class="app-bar"><span style="width:${share}%"></span></div></td><td>${active}</td><td>${locks?`<span class="severity warning">${locks}</span>`:'0'}</td></tr>`;
  }).join('');
}
function renderPatterns(items) {
  const node=$('pattern-list');
  if(!items?.length){node.innerHTML='<div class="empty-state">No recurring incident records in the last seven days. Patterns build as incidents accumulate.</div>';return}
  node.innerHTML=items.map(item=>`<div class="pattern-item"><div class="pattern-main"><span class="pattern-icon">↗</span><div class="pattern-name"><strong>${esc(item.title||niceKind(item.kind))}</strong><span>${esc(item.open_count||0)} open · last seen ${esc(fmtTime(item.last_seen))}</span></div></div><div class="pattern-count">${esc(item.incident_count)}<small>INCIDENTS</small></div></div>`).join('');
}
function renderIncidents(items) {
  $('nav-open-count').textContent=items.filter(i=>i.status==='open').length;
  const body=$('incident-rows');
  if(!items?.length){body.innerHTML='<tr><td colspan="7" class="empty-state">No matching incident records. Run the controlled long-query, idle-transaction or blocking tests to generate evidence.</td></tr>';return}
  body.innerHTML=items.map(item=>`<tr data-incident="${esc(item.id)}"><td><div class="incident-title"><i class="incident-marker ${esc(item.severity)}"></i>${esc(item.title)}</div><span class="incident-sub">${esc(item.db_name)} · ${esc(niceKind(item.kind))}</span></td><td><span class="severity ${esc(item.severity)}">${esc(item.severity)}</span></td><td><span class="status-badge ${esc(item.status)}">${esc(item.status)}</span></td><td>${esc(fmtTime(item.first_seen))}</td><td>${esc(fmtTime(item.last_seen))}</td><td>${esc(item.observation_count)}</td><td class="row-arrow">›</td></tr>`).join('');
  body.querySelectorAll('tr[data-incident]').forEach(row=>row.addEventListener('click',()=>openIncident(row.dataset.incident)));
}
function renderEvidence(samples) {
  const list=$('evidence-list');
  if(!samples?.length){list.innerHTML='<div class="empty-state">No evidence captured yet.</div>';return}
  list.innerHTML=[...samples].reverse().slice(0,7).map(s=>{
    const count=(s.detections||[]).length,host=s.host_metrics||{};
    const title=count?`${count} rule-based finding(s) observed`:'Successful snapshot · no configured rule triggered';
    const summary=`${s.db_name} · ${s.active_sessions} active · ${s.total_client_backends}/${s.max_connections} connections · ${s.lock_waiters} lock waits · host CPU ${host.cpu_percent==null?'—':`${host.cpu_percent}%`}`;
    return `<div class="evidence-item"><div class="evidence-time">${esc(fmtTime(s.captured_at))}</div><div class="evidence-marker"></div><div><div class="evidence-title">${esc(title)}</div><div class="evidence-sub">${esc(summary)}</div></div><div class="evidence-count">SAMPLE #${esc(s.id)}</div></div>`;
  }).join('');
}
function renderComparison(analysis) {
  const periods=analysis?.comparison?.periods||{};
  const keys=[['total_client_backends','Connections'],['active_sessions','Active sessions'],['lock_waiters','Lock waiters'],['idle_in_transaction','Idle in transaction'],['host_cpu_percent','Collector-host CPU %'],['host_memory_percent','Collector-host memory %'],['host_disk_percent','Collector-host root disk %']];
  const value=(period,key)=>{const m=periods?.[period]?.metrics?.[key];if(!m||!m.observations||m.last==null)return '—';return key.endsWith('_percent')?`${Number(m.last).toFixed(1)}%`:String(Number.isInteger(Number(m.last))?Number(m.last):m.last)};
  const n=name=>Number(periods?.[name]?.sample_count||0);
  const rows=keys.map(([key,label])=>`<tr><td>${esc(label)}</td><td>${esc(value('before',key))}</td><td>${esc(value('during',key))}</td><td>${esc(value('after',key))}</td></tr>`).join('');
  return `<div class="analysis-section"><div class="analysis-section-heading"><div><h3>Before / during / after</h3><p>Last retained snapshot per period. These are sampled values, not continuous measurements.</p></div></div><div class="comparison-summary"><span>Before <strong>${n('before')}</strong></span><span>During <strong>${n('during')}</strong></span><span>After <strong>${n('after')}</strong></span></div><div class="comparison-scroll"><table class="comparison-table"><thead><tr><th>METRIC</th><th>BEFORE</th><th>DURING</th><th>AFTER</th></tr></thead><tbody>${rows}</tbody></table></div><p class="analysis-foot">${esc(analysis?.comparison?.definition||'')}</p></div>`;
}
function renderTimeline(events) {
  if(!events?.length)return '<p class="analysis-empty">No surrounding timeline events could be reconstructed from retained samples.</p>';
  return `<div class="incident-timeline">${events.map(event=>`<div class="timeline-event ${esc(event.event_type)}"><div class="timeline-time">${esc(fmtTime(event.timestamp))}</div><div class="timeline-node"></div><div class="timeline-copy"><strong>${esc(event.title)}</strong><p>${esc(event.description)}</p>${event.sample_id?`<span class="timeline-source">Evidence sample #${esc(event.sample_id)}</span>`:''}</div></div>`).join('')}</div>`;
}
function renderHypotheses(items) {
  if(!items?.length)return '<p class="analysis-empty">No rule-specific hypothesis is available.</p>';
  return items.map(item=>`<article class="hypothesis-card"><div class="hypothesis-heading"><strong>${esc(item.title)}</strong><span class="confidence ${esc(item.confidence)}">${esc(item.confidence)} confidence</span></div><div class="hypothesis-label">HYPOTHESIS · NOT A VERIFIED ROOT CAUSE</div><div class="hypothesis-columns"><div><h4>Supporting evidence</h4><ul>${(item.supporting_evidence||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div><div><h4>Missing / alternative evidence</h4><ul>${(item.missing_or_alternative_evidence||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div></div><h4>Recommended next checks</h4><ol>${(item.next_checks||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ol></article>`).join('');
}
function renderCrossLayer(cross) {
  cross=cross||{};const host=cross.host_context||{};
  const metric=(key,label)=>{const m=host[key]||{};return `<p><strong>${esc(label)}:</strong> average ${m.average==null?'—':`${m.average}%`} · peak ${m.max==null?'—':`${m.max}%`} · ${m.observations||0} sample(s)</p>`};
  const signals=(cross.cross_layer_signals||[]).length?(cross.cross_layer_signals||[]).map(s=>`<div class="cross-signal"><strong>${esc(s.name)}:</strong> ${esc(s.detail)}</div>`).join(''):'<p>No configured high-resource temporal signal was observed in the incident-triggering samples, or host data was unavailable.</p>';
  const apps=(cross.observed_applications||[]).length?(cross.observed_applications||[]).map(a=>`<div class="app-context-row"><span><strong>${esc(a.application_name)}</strong><br/>PIDs ${esc((a.pids||[]).join(', ')||'not retained')}</span><span>peak sessions ${esc(a.peak_sessions)} · active ${esc(a.peak_active_sessions)} · lock waits ${esc(a.peak_lock_waiters)}</span></div>`).join(''):'<p>No application-name breakdown was retained for triggering samples.</p>';
  return `<div class="analysis-section"><div class="analysis-section-heading"><div><h3>Cross-layer context</h3><p>Supporting context only. Temporal overlap does not establish causation.</p></div></div><div class="cross-grid"><div class="cross-card"><h4>Collector-host resource signals</h4>${metric('cpu_percent','CPU')}${metric('memory_percent','Memory')}${metric('disk_percent','Root disk')}<p class="analysis-foot">${esc(host.note||'Host data may not describe the PostgreSQL server.')}</p></div><div class="cross-card"><h4>Application workloads in triggering samples</h4>${apps}</div></div><h4>Context signals</h4>${signals}<p class="analysis-foot">${esc(cross.application_context_note||'Application names are client-supplied metadata and do not quantify end-user impact.')}</p></div>`;
}
async function openIncident(id) {
  try {
    const data=await api(`/api/incidents/${encodeURIComponent(id)}`),item=data.incident,analysis=data.analysis||{};selectedIncidentId=id;
    $('detail-title').textContent=item.title;$('detail-subtitle').textContent=`${item.db_name} · ${niceKind(item.kind)} · ${item.observation_count} sampled observation(s)`;
    const details=item.details||{};
    const facts=Object.entries(details).filter(([k,v])=>k!=='sessions'&&typeof v!=='object').map(([k,v])=>`<div class="detail-fact"><strong>${esc(niceKind(k))}:</strong> ${esc(v)}</div>`).join('');
    const sessions=(details.sessions||[]).slice(0,15).map(s=>`<div class="detail-fact"><strong>PID ${esc(s.pid)}</strong> · ${esc(s.state||'unknown')} · ${esc(s.application_name||'unnamed application')} · query age ${esc(s.query_age_seconds??'—')}s · transaction age ${esc(s.xact_age_seconds??'—')}s · blocker PIDs ${esc((s.blocking_pids||[]).join(', ')||'none')}</div>`).join('');
    const coverage=analysis.coverage||{},notes=(coverage.notes||[]).map(x=>`<li>${esc(x)}</li>`).join(''),gaps=(coverage.collection_gaps||[]).map(x=>`<li>${esc(x.gap_seconds)}s collection gap: ${esc(fmtTime(x.from))} → ${esc(fmtTime(x.to))}</li>`).join('');
    const impact=analysis.impact_assessment||{};
    $('detail-body').innerHTML=`
      <div class="detail-status-strip"><span class="severity ${esc(item.severity)}">${esc(item.severity)}</span><span class="status-badge ${esc(item.status)}">${esc(item.status)}</span><span class="status-badge">ROOT CAUSE NOT CONFIRMED</span></div>
      <div class="detail-fact"><strong>First observed:</strong> ${esc(fmtTime(item.first_seen))} · <strong>Last observed:</strong> ${esc(fmtTime(item.last_seen))}<br/><strong>Rule observations:</strong> ${esc(item.observation_count)} · <strong>Context samples:</strong> ${esc(data.samples.length)}</div>
      <div class="analysis-section"><div class="analysis-section-heading"><div><h3>What we know</h3><p>Facts preserved by successful PostgreSQL collector samples.</p></div></div><p class="analysis-callout">${esc(item.summary)}</p>${facts}${sessions?`<h4>Session evidence</h4>${sessions}`:''}</div>
      <div class="analysis-section"><div class="analysis-section-heading"><div><h3>Incident timeline</h3><p>Recorded observations before, during and after the rule-triggering period.</p></div></div>${renderTimeline(analysis.timeline||[])}</div>
      ${renderComparison(analysis)}
      ${renderCrossLayer(analysis.cross_layer_context)}
      <div class="analysis-section"><div class="analysis-section-heading"><div><h3>Investigation hypotheses</h3><p>Rule-based explanations with supporting and missing evidence.</p></div></div>${renderHypotheses(analysis.hypotheses||[])}</div>
      <div class="analysis-section"><div class="analysis-section-heading"><div><h3>Evidence coverage</h3><p>Missing collection windows are disclosed, not interpreted as proof of absence.</p></div></div><div class="coverage-chips"><span>Before <strong>${esc(coverage.before_samples??0)}</strong></span><span>During <strong>${esc(coverage.during_samples??0)}</strong></span><span>After <strong>${esc(coverage.after_samples??0)}</strong></span><span>Cadence <strong>${esc(coverage.estimated_interval_seconds??'—')}s</strong></span></div><ul class="coverage-notes">${notes}${gaps}</ul></div>
      <div class="analysis-section impact-section"><div class="analysis-section-heading"><div><h3>Business impact</h3><p>End-user and business outcomes require application telemetry.</p></div><span class="status-badge">NOT MEASURED</span></div><p>${esc(impact.message||'Business impact has not been measured.')}</p></div>`;
    $('modal-backdrop').hidden=false;
  }catch(error){toast(`Could not open incident: ${error.message}`)}
}
function closeModal(){$('modal-backdrop').hidden=true}
async function refresh(){
  if(refreshBusy)return;refreshBusy=true;
  try{
    const [data,analytics,evidence]=await Promise.all([api('/api/overview'),api('/api/analytics'),api('/api/evidence?limit=30')]);
    renderConnection(data);renderMetrics(data.latest,data.counts);lineChart(data.trend||[]);renderHost(analytics.host_latest);renderApplications(analytics.applications||[]);renderPatterns(analytics.incident_patterns_7d||[]);renderEvidence(evidence.items||[]);
    const filter=$('incident-filter').value;
    const incidentData=filter==='open'?{items:data.incidents||[]}:await api(`/api/incidents?status=${filter}`);
    renderIncidents(incidentData.items||[]);
  }catch(error){toast(`Dashboard refresh failed: ${error.message}`)}finally{refreshBusy=false}
}
$('collect-now').addEventListener('click',async()=>{
  const button=$('collect-now');button.disabled=true;button.innerHTML='<span class="button-icon">↻</span> Capturing…';
  try{const result=await api('/api/collect',{method:'POST'});toast(`Captured PostgreSQL evidence from ${result.db_name}`);await refresh()}
  catch(error){toast(`Capture failed: ${error.message}`);await refresh()}
  finally{button.disabled=false;button.innerHTML='<span class="button-icon">↻</span> Capture now'}
});
$('incident-filter').addEventListener('change',async()=>{try{const data=await api(`/api/incidents?status=${$('incident-filter').value}`);renderIncidents(data.items||[])}catch(e){toast(e.message)}});
$('close-modal').addEventListener('click',closeModal);$('close-modal-bottom').addEventListener('click',closeModal);
$('modal-backdrop').addEventListener('click',e=>{if(e.target===$('modal-backdrop'))closeModal()});
$('download-report').addEventListener('click',()=>{if(selectedIncidentId)window.location.href=`/api/incidents/${encodeURIComponent(selectedIncidentId)}/report.md`});
document.querySelectorAll('.nav-item').forEach(link=>link.addEventListener('click',()=>{document.querySelectorAll('.nav-item').forEach(item=>item.classList.remove('active'));link.classList.add('active')}));
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('modal-backdrop').hidden)closeModal()});
refresh();window.setInterval(refresh,5000);

import { useEffect, useState } from "react";

const root = "/api/admin/marketing";
const destinations = ["/market", "/heatmap", "/issuers", "/news"].flatMap(path => [path, "/uz"+path]);

export async function marketingRequest(apiFetch, path, method, body) {
  const options = method ? {method, headers: {"Content-Type":"application/json"}, body:JSON.stringify(body)} : {};
  const response = await apiFetch(root + path, options);
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

export function statusName(t, status) {
  const names = {
    published: t("Опубликовано", "E’lon qilindi", "Published"),
    skipped: t("Пропущено", "O‘tkazildi", "Skipped"),
    edited: t("Отредактировано", "Tahrirlandi", "Edited"),
    draft: t("Черновик", "Qoralama", "Draft"),
    approved: t("Утверждено", "Tasdiqlandi", "Approved")
  };
  return names[status];
}

function PathSelect({label, value, onChange, disabled}) {
  return <label>{label}<select value={value} disabled={disabled} onChange={e=>onChange(e.target.value)}>
    {destinations.map(path=><option key={path}>{path}</option>)}
  </select></label>;
}

function PlanEditor({plan, t, run, busy}) {
  const [audience, setAudience] = useState(plan.audience);
  const [channel, setChannel] = useState(plan.channel);
  const [destination, setDestination] = useState(plan.destination);
  const [actions, setActions] = useState(plan.schedule.join("\n"));
  const locked = plan.status==="approved";
  const save = approve => run("/plans/"+plan.id, "PUT", {audience, channel, destination,
    schedule:actions.split("\n").map(line=>line.trim()).filter(Boolean), approve});
  return <article className="marketing-record">
    <h4>{plan.goal}</h4><p>{statusName(t,plan.status)}</p>
    <fieldset disabled={locked || busy}>
      <label>{t("Аудитория","Auditoriya","Audience")}<input value={audience} maxLength={450} onChange={e=>setAudience(e.target.value)}/></label>
      <label>{t("Канал","Kanal","Channel")}<input value={channel} maxLength={180} onChange={e=>setChannel(e.target.value)}/></label>
      <PathSelect label={t("Целевая страница","Maqsad sahifasi","Destination")} value={destination} onChange={setDestination}/>
      <label>{t("Действия на неделю","Haftalik ishlar","Weekly actions")}<textarea rows={5} value={actions} onChange={e=>setActions(e.target.value)}/></label>
    </fieldset>
    {locked ? <a href={plan.link} target="_blank" rel="noreferrer">{t("Ссылка кампании","Kampaniya havolasi","Campaign link")}</a> :
      <div className="marketing-actions">
        <button className="admin-btn" disabled={busy} onClick={()=>save(false)}>{t("Сохранить план","Rejani saqlash","Save plan")}</button>
        <button className="admin-btn accent" disabled={busy} onClick={()=>save(true)}>{t("Утвердить план","Rejani tasdiqlash","Approve plan")}</button>
      </div>}
  </article>;
}

function Weekly({report, t}) {
  const weekly = Object.entries(report?.weekly || {}).sort((a,b)=>b[1].visits-a[1].visits);
  const leak = weekly.filter(([,m])=>m.visits>m.continued)
    .sort((a,b)=>(b[1].visits-b[1].continued)-(a[1].visits-a[1].continued))[0];
  const metricNames = [t("Кампания","Kampaniya","Campaign"), t("Визиты","Tashriflar","Visits"),
    t("Читатели","O‘quvchilar","Readers"),t("Страницы","Sahifalar","Pages"),
    t("Открыли ещё страницу","Keyingi sahifaga o‘tdi","Read another page"), t("Вернулись","Qaytdi","Returned")];
  return <section className="panel marketing-module">
    <h3>{t("Результаты за 7 дней","7 kunlik natijalar","Last seven days")}</h3>
    {!report?.available ? <p>{t("Аналитика недоступна.","Tahlil hozir mavjud emas.","Analytics unavailable.")}</p> :
      !weekly.length ? <p>{t("Здесь появятся опубликованные посты и утверждённые кампании.","Bu yerda e’lon qilingan post va tasdiqlangan kampaniyalar ko‘rinadi.","Published posts and approved campaigns will appear here.")}</p> : <>
        <p>{t("Визит относится к ссылке входа. Страницы считаются один раз за визит. Возврат — следующий визит того же браузера до конца периода.",
          "Tashrif kirish havolasiga bog‘lanadi. Har sahifa tashrifda bir marta sanaladi. Qaytish — davr oxirigacha shu brauzerdagi keyingi tashrif.",
          "Credit goes to the landing link. Pages count once per visit. Returns count readers who visited again before the end of the period.")}</p>
        <div className="marketing-table"><table><thead><tr>{metricNames.map(label=><th key={label}>{label}</th>)}</tr></thead>
          <tbody>{weekly.map(([tag,m])=><tr key={tag}><td>{tag}</td>{["visits","readers","pages","continued","returned"].map(k=><td key={k}>{m[k]}</td>)}</tr>)}</tbody></table></div>
        {leak && <aside><strong>{leak[0]}</strong><p>{t(
          `${leak[1].visits-leak[1].continued} из ${leak[1].visits} визитов завершились на первой странице. Проверьте, помогает ли другая целевая страница продолжить чтение.`,
          `${leak[1].visits} tashrifdan ${leak[1].visits-leak[1].continued} tasi birinchi sahifada tugadi. Boshqa kirish sahifasi o‘qishni davom ettirishga yordam berishini sinang.`,
          `${leak[1].visits-leak[1].continued} of ${leak[1].visits} visits ended on the landing page. Test a different landing page and compare how often readers open a second page.`)}</p></aside>}
      </>}
  </section>;
}

export function MarketingWorkspace({t, apiFetch, language, refresh}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);
  const [attempt, retry] = useState(0);
  const [goal,setGoal] = useState("");
  const [name,setName] = useState("");
  const [a,setA] = useState("/market"), [b,setB] = useState("/heatmap");
  useEffect(()=>{
    let live=true;
    marketingRequest(apiFetch,"/workspace").then(result=>{if(live) {setData(result);setError(false);}})
      .catch(()=>{if(live) setError(true);});
    return ()=>{live=false;};
  },[apiFetch, refresh, attempt]);
  async function run(path, method, body) {
    setLoading(true); setError(false);
    try {
      await marketingRequest(apiFetch,path,method,body);
      if(path==="/plans") setGoal("");
      if(path==="/experiments") setName("");
      retry(v=>v+1);
    } catch {setError(true);}
    finally {setLoading(false);}
  }
  return <div className="marketing-workspace">
    {error && <div role="alert">{t("Не удалось выполнить запрос. Проверьте данные и повторите.","So‘rov bajarilmadi. Ma’lumotni tekshiring va qayta urining.","Request failed. Check your entries and try again.")}
      <button className="admin-btn" onClick={()=>retry(v=>v+1)}>{t("Обновить","Yangilash","Refresh")}</button></div>}
    {data && <>
      <Weekly report={data.report} t={t}/>
      <section className="panel marketing-module"><h3>{t("План кампании","Kampaniya rejasi","Campaign planner")}</h3>
        <form onSubmit={e=>{e.preventDefault();run("/plans","POST",{goal,language});}}>
          <label>{t("Цель кампании","Kampaniya maqsadi","Campaign goal")}<textarea rows={2} minLength={5} required maxLength={700} value={goal} onChange={e=>setGoal(e.target.value)}/></label>
          <button className="admin-btn accent" disabled={loading || goal.trim().length<5}>{t("Создать план","Reja yaratish","Generate plan")}</button>
        </form>
        {loading && <p role="status">{t("Обрабатываем запрос…","So‘rov bajarilmoqda…","Working…")}</p>}
        {data.plans?.map(plan=><PlanEditor key={plan.id} {...{plan,t,run,busy:loading}}/>)}
      </section>
      <section className="panel marketing-module"><h3>{t("Эксперименты","Tajribalar","Experiments")}</h3>
        <p>{t("Одна ссылка распределяет читателей между страницами. Сравниваем первые 100 браузеров в каждой группе через 24 часа: открыли ли они вторую страницу за первый визит.",
          "Bitta havola o‘quvchilarni ikki sahifaga taqsimlaydi. Har guruhning dastlabki 100 brauzeri uchun 24 soatdan keyin birinchi tashrifda ikkinchi sahifa ochilganini solishtiramiz.",
          "Share one link to randomly assign readers to two destinations. After 24 hours, compare how often the first 100 browsers per group opened another page during their first visit.")}</p>
        <form onSubmit={e=>{e.preventDefault();run("/experiments","POST",{name,a,b});}}>
          <label>{t("Название эксперимента","Tajriba nomi","Experiment name")}<input required minLength={2} maxLength={140} value={name} onChange={e=>setName(e.target.value)}/></label>
          <PathSelect label={t("Страница A","A sahifa","Destination A")} value={a} onChange={setA}/>
          <PathSelect label={t("Страница B","B sahifa","Destination B")} value={b} onChange={setB}/>
          <button className="admin-btn" disabled={loading || a===b || name.trim().length<2}>{t("Начать эксперимент","Tajribani boshlash","Start experiment")}</button>
        </form>
        {data.experiments?.map(trial=>{
          const m=data.report?.trials?.[trial.id];
          const verdict={a:t("Выше у A","A yuqoriroq","A performed better"), b:t("Выше у B","B yuqoriroq","B performed better"),
            collecting:t("Собираем данные","Dalillar yig‘ilmoqda","Collecting evidence"), inconclusive:t("Различие не установлено","Farq aniqlanmadi","No clear difference")};
          return <article className="marketing-record" key={trial.id}><h4>{trial.name}</h4>
            <a href={trial.link} target="_blank" rel="noreferrer">{t("Ссылка эксперимента","Tajriba havolasi","Experiment link")}</a>
            <p>{m ? verdict[m.result] : t("Аналитика недоступна","Tahlil mavjud emas","Analytics unavailable")}</p>
            {["a","b"].map(arm=><div key={arm}>{arm.toUpperCase()} · {trial[arm]} {m && ` · ${m[arm][0]} / ${m[arm][1]}`}</div>)}
          </article>;})}
      </section>
      {!!data.history?.length && <section className="panel marketing-module"><h3>{t("Решения редактора","Muharrir qarorlari","Editorial history")}</h3>
        {data.history.map(row=><p key={row.story_id+row.edition}>{row.title} · {row.edition.toUpperCase()} · {statusName(t,row.status)} {row.reason && " · "+row.reason}</p>)}
      </section>}
    </>}
  </div>;
}

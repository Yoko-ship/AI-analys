import { useEffect, useMemo, useRef, useState } from "react";
import { campaignQr, drawCampaignCard } from "./campaignCard.js";

const api = "/api/admin/marketing/campaign-posts";
const features = {
  "/market": {ru:"Котировки", uz:"Kotirovkalar", en:"Market quotes"},
  "/heatmap": {ru:"Тепловая карта", uz:"Issiqlik xaritasi", en:"Market heatmap"},
  "/issuers": {ru:"Справочник эмитентов", uz:"Emitentlar katalogi", en:"Issuer directory"},
  "/news": {ru:"Новости рынка", uz:"Bozor yangiliklari", en:"Market news"},
};

async function request(apiFetch, path, method = "GET", data) {
  const response = await apiFetch(api + path, {method, ...(data && {body:JSON.stringify(data)})});
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

function CampaignEditor({post, t, apiFetch, metrics, onSaved, onReload, onDirty}) {
  const [headline, setHeadline] = useState(post.headline);
  const [body, setBody] = useState(post.body);
  const [brief, setBrief] = useState("");
  const [suggestion, setSuggestion] = useState(null);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const canvas = useRef(null);
  const shareText = useRef(null);
  const dirty = headline !== post.headline || body !== post.body;
  const published = post.status === "published";
  const valid = headline.trim().length >= 3 && body.trim().length >= 10;
  const text = [headline.trim(), body.trim(), post.link].join("\n\n");
  const feature = features[post.destination][post.edition];
  const qr = useMemo(()=>campaignQr(post.link),[post.link]);
  useEffect(()=>{onDirty(dirty || Boolean(busy));},[dirty,busy,onDirty]);
  useEffect(()=>{
    if (canvas.current) drawCampaignCard(canvas.current, headline, feature, post.edition, post.link, qr);
  },[headline,feature,post.edition,post.link,qr]);
  async function perform(action) {
    setBusy(action); setError(""); setNotice("");
    try {
      if (action === "suggest") {
        setSuggestion(await request(apiFetch, "/" + post.id + "/suggest", "POST", {brief,version:post.version}));
      } else {
        const saved = await request(apiFetch, "/" + post.id, "PUT", {headline,body,version:post.version,publish:action==="publish"});
        onSaved(saved);
      }
    } catch (e) { setError(e.message==="409"?"conflict":action==="suggest"?"model":"save"); }
    finally { setBusy(""); }
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setNotice(t("Пост скопирован","Post nusxalandi","Post copied"));
    } catch {
      shareText.current.hidden=false;
      shareText.current.focus(); shareText.current.select();
      setNotice(t("Скопируйте выделенный текст.","Belgilangan matndan nusxa oling.","Copy the selected text."));
    }
  }
  function download() {
    canvas.current.toBlob(blob=>{
      if (!blob) {setError("image"); return;}
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href=url; a.download="uzstock-"+post.destination.slice(1)+"-"+post.edition+"-"+post.id+".png";
      a.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    }, "image/png");
  }
  const shareUrl = post.channel === "telegram"
    ? "https://t.me/share/url?" + new URLSearchParams({url:post.link,text:headline.trim()+"\n\n"+body.trim()})
    : "https://www.linkedin.com/sharing/share-offsite/?" + new URLSearchParams({url:post.link});
  return <article className="campaign-editor">
    <div className="campaign-fields">
      <label>{t("Заголовок","Sarlavha","Headline")}
        <input lang={post.edition} maxLength={100} value={headline} readOnly={published} disabled={Boolean(busy)} onChange={e=>setHeadline(e.target.value)}/></label>
      <label>{t("Текст поста","Post matni","Post text")}
        <textarea lang={post.edition} rows={4} maxLength={1800} value={body} readOnly={published} disabled={Boolean(busy)} onChange={e=>setBody(e.target.value)}/></label>
      {!published && <>
        <label>{t("Пожелания для ИИ","AI uchun ko‘rsatma","Instructions for the AI")}
          <input value={brief} maxLength={400} disabled={Boolean(busy)} onChange={e=>setBrief(e.target.value)}
            placeholder={t("Например, объяснить новичку","Masalan, yangi o‘quvchiga tushuntiring","For example, write for a first-time investor")}/></label>
        <div className="marketing-actions">
          <button className="admin-btn" disabled={Boolean(busy)||dirty} onClick={()=>perform("suggest")}>{t("Предложить текст","Matn taklif qilish","Suggest copy")}</button>
          <button className="admin-btn accent" disabled={!dirty||!valid||Boolean(busy)} onClick={()=>perform("save")}>{t("Сохранить черновик","Qoralamani saqlash","Save draft")}</button>
          {dirty && <button className="admin-btn" disabled={Boolean(busy)} onClick={()=>{setHeadline(post.headline);setBody(post.body);setSuggestion(null);}}>{t("Отменить правки","Tahrirni bekor qilish","Discard edits")}</button>}
        </div>
        {busy==="suggest" && <p role="status">{t("ИИ готовит вариант…","AI variant tayyorlamoqda…","Preparing a suggestion…")}</p>}
        {suggestion && <aside className="campaign-suggestion"><strong lang={post.edition}>{suggestion.headline}</strong><p lang={post.edition}>{suggestion.body}</p>
          <button className="admin-btn" disabled={Boolean(busy)} onClick={()=>{setHeadline(suggestion.headline);setBody(suggestion.body);setSuggestion(null);}}>{t("Использовать вариант","Variantni tanlash","Use suggestion")}</button>
          <button className="admin-btn" onClick={()=>setSuggestion(null)}>{t("Оставить свой текст","O‘z matnimni qoldirish","Keep original")}</button></aside>}
      </>}
      {error && <div role="alert">{error==="model" ? t("ИИ недоступен. Черновик можно редактировать и копировать.","AI mavjud emas. Qoralamani tahrirlash va nusxalash mumkin.","AI is unavailable. You can edit and share the saved draft.")
        : error==="conflict" ? t("Черновик изменился в другой вкладке.","Qoralama boshqa oynada o‘zgardi.","This draft changed in another tab.")
        : t("Не удалось выполнить действие. Повторите попытку.","Amal bajarilmadi. Qayta urinib ko‘ring.","That action failed. Please try again.")}
        {error==="conflict" && <button className="admin-btn" onClick={onReload}>{t("Загрузить сохранённый текст","Saqlangan matnni yuklash","Load saved version")}</button>}</div>}
    </div>
    <div className="campaign-output">
      <canvas ref={canvas} width={1200} height={630} role="img" aria-label={feature+" · "+headline}/>
      <div className="marketing-actions"><button className="admin-btn" disabled={!valid} onClick={download}>{t("Скачать изображение","Rasmni yuklab olish","Download image")}</button>
        <a href={post.link} target="_blank" rel="noreferrer">{t("Целевая страница","Maqsad sahifasi","View landing page")}</a></div>
      <div className="marketing-actions"><button className="admin-btn accent" disabled={!valid} onClick={copy}>{t("Скопировать пост","Postni nusxalash","Copy post")}</button>
        {valid && <a href={shareUrl} target="_blank" rel="noreferrer">{post.channel==="telegram" ? t("Открыть в Telegram","Telegram’da ochish","Open in Telegram") : t("Открыть в LinkedIn","LinkedIn’da ochish","Open in LinkedIn")}</a>}</div>
      <textarea hidden ref={shareText} readOnly value={text} aria-label={t("Текст со ссылкой","Havolali matn","Post with tracking link")}/>
      {post.channel==="linkedin" && <small>{t("Вставьте скопированный текст в LinkedIn. Изображение можно прикрепить отдельно.",
        "Nusxalangan matnni LinkedIn’ga joylang. Rasmni alohida biriktirishingiz mumkin.",
        "Paste the copied text into LinkedIn. You can attach the downloaded image there.")}</small>}
      <span role="status">{notice}</span>
      {published ? <div className="campaign-results"><strong>{t("Опубликовано","E’lon qilindi","Published")}</strong>
        {metrics ? <p>{t("За 7 дней","7 kun ichida","Last seven days")} · {t(`визиты: ${metrics.visits}`,`${metrics.visits} tashrif`,`${metrics.visits} visits`)} · {t(`вернулось читателей: ${metrics.returned}`,`qaytgan o‘quvchilar: ${metrics.returned}`,`${metrics.returned} returning readers`)}</p>
        : <p>{t("Результаты пока недоступны.","Natijalar hozircha mavjud emas.","Results are currently unavailable.")}</p>}</div>
      : <div className="campaign-publish"><p>{t("После размещения отметьте пост, чтобы увидеть переходы за неделю.","Joylaganingizdan so‘ng haftalik tashriflarni ko‘rish uchun postni belgilang.","After sharing, mark the post as published to see its seven-day results.")}</p>
        <button className="admin-btn" disabled={!valid||Boolean(busy)} onClick={()=>perform("publish")}>{t("Отметить публикацию","Chop etilganini belgilash","Mark as published")}</button></div>}
    </div>
  </article>;
}

export function FeatureCampaigns({apiFetch, language, t, plans, report, onPublish}) {
  const [items, setItems] = useState(null);
  const [selected, select] = useState("");
  const [destination, setDestination] = useState("/heatmap");
  const [edition, setEdition] = useState(language);
  const [channel, setChannel] = useState("telegram");
  const [planId, setPlanId] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [attempt, retry] = useState(0);
  const [message, setMessage] = useState("");
  const createKey = useRef(null);
  const approved = plans.filter(plan=>plan.status==="approved");
  const plan = approved.find(p=>p.id===planId);
  const path = plan ? plan.destination.replace(/^\/uz(?=\/)/,"") : destination;
  useEffect(()=>{
    let active = true;
    request(apiFetch,"").then(data=>{
      if (active) {setItems(data.items || []);setError(false);}
    }).catch(()=>{if(active)setError(true);});
    return ()=>{active=false;};
  },[apiFetch,attempt]);
  const current = items?.find(row=>row.id===selected) ?? items?.[0];
  async function create() {
    if (busy) return;
    setBusy(true);setError(false);setMessage("");
    const brief = {destination:path,edition,channel,plan_id:plan?.id || null};
    const fingerprint = JSON.stringify(brief);
    if (createKey.current?.fingerprint!==fingerprint) createKey.current={fingerprint,id:crypto.randomUUID()};
    try {
      const post = await request(apiFetch,"","POST",{...brief,request_id:createKey.current.id});
      setItems(prev=>[post,...(prev || []).filter(row=>row.id!==post.id)]);select(post.id);
      createKey.current=null;
    } catch {setError(true);}
    finally {setBusy(false);}
  }
  function saved(post) {
    setItems(prev=>prev.map(row=>row.id===post.id?post:row));setDirty(false);
    setMessage(post.status==="published"?"":t("Черновик сохранён","Qoralama saqlandi","Draft saved"));
    if (post.status==="published") onPublish();
  }
  return <section className="panel marketing-module feature-campaigns" aria-labelledby="feature-campaign-heading">
    <h2 id="feature-campaign-heading">{t("Продвижение разделов","Sayt bo‘limlarini targ‘ib qilish","Feature campaigns")}</h2>
    <p>{t("Пригласите читателей попробовать один инструмент UZStock. Подготовьте текст и карточку со ссылкой для учёта переходов.",
      "O‘quvchilarni UZStock vositalaridan birini sinab ko‘rishga taklif qiling. Post matni, rasmi va tashriflarni sanaydigan havolani tayyorlang.",
      "Invite readers to try a UZStock tool. Create a post, a share image, and a link that tracks visits.")}</p>
    <form className="campaign-brief" onSubmit={e=>{e.preventDefault();create();}}>
      {approved.length>0 && <label>{t("Утверждённый план","Tasdiqlangan reja","Approved plan")}<select value={planId} onChange={e=>setPlanId(e.target.value)}>
        <option value="">{t("Без плана","Rejasiz","Start without a plan")}</option>{approved.map(p=><option key={p.id} value={p.id}>{p.goal}</option>)}</select></label>}
      <label>{t("Раздел сайта","Sayt bo‘limi","Site feature")}<select value={path} disabled={!!plan} onChange={e=>setDestination(e.target.value)}>
        {Object.entries(features).map(([k,v])=><option key={k} value={k}>{v[language]}</option>)}</select></label>
      <label>{t("Язык поста","Post tili","Post language")}<select value={edition} onChange={e=>setEdition(e.target.value)}>
        <option value="uz">O‘zbekcha</option><option value="ru">Русский</option><option value="en">English</option></select></label>
      <label>{t("Канал публикации","Nashr kanali","Publishing channel")}<select value={channel} onChange={e=>setChannel(e.target.value)}>
        <option value="telegram">Telegram</option><option value="linkedin">LinkedIn</option></select></label>
      <button className="admin-btn accent" disabled={busy||dirty||items===null}>{t("Создать пост","Post yaratish","Create post")}</button>
    </form>
    {error && <p role="alert">{t("Не удалось загрузить или сохранить посты.","Postlarni yuklash yoki saqlash imkoni bo‘lmadi.","Could not load or save campaign posts.")} <button className="admin-btn" onClick={()=>retry(n=>n+1)}>{t("Обновить","Yangilash","Refresh")}</button></p>}
    {items===null && !error && <p role="status">{t("Загружаем посты…","Postlar yuklanmoqda…","Loading posts…")}</p>}
    {current && <>
      <label className="campaign-library">{t("Сохранённые посты","Saqlangan postlar","Saved posts")}
        <select disabled={dirty||busy} value={current.id} onChange={e=>{select(e.target.value);setMessage("");}}>
          {items.map(p=><option key={p.id} value={p.id}>{p.headline} · {p.edition.toUpperCase()} · {p.channel==="telegram"?"Telegram":"LinkedIn"}</option>)}</select></label>
      <CampaignEditor key={current.id+":"+current.version} post={current} {...{t,apiFetch}} metrics={report?.available ? report.weekly?.[current.tag] : null}
        onSaved={saved} onReload={()=>retry(n=>n+1)} onDirty={setDirty}/>
    </>}
    {message && <span role="status">{message}</span>}
  </section>;
}

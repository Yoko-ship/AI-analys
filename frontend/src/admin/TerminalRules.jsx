import React from "react";
import { words } from "../shared/TerminalTables.jsx";
const samples={financial_formula:{code:'combined_ratio',numerators:['insurance_service_cost','expenses'],denominators:['revenue'],unit:'percent',basis:'previous',test_cases:[{values:{insurance_service_cost:45,expenses:20,revenue:100},organization_type:'insurance',expected:65},{values:{expenses:20,revenue:0},organization_type:'insurance',expected:null}]},formula:{code:'P1',numerators:['form2:c270'],denominators:['form1:c480'],percent:true,test_cases:[{inputs:{'form2:c270':'20','form1:c480':'100'},expected:'20'},{inputs:{},expected:null}]},template:{code:'industry23',oked_prefix:'23',template:'cement',test_cases:[{snapshot:{organization_type:'non_financial'},issuer:{oked_code:'23900'},expected:{template_resolution:{selected_template:'cement'}}}]},valuation:{code:'terminal_fv',as_of:'2026-10-15',key_rate:14,default_spread:3.06,equity_premium:8.89,growth:9.8,test_cases:[{base:{kind:'bank',roe:20},peers:[],expected:{required_return:19.83}}]}};
export function TerminalRules({apiFetch,lang,data}) {
  const t=(ru,uz,en)=>words(lang,ru,uz,en);
  const [category,setCategory]=React.useState('formula');
  const [config,setConfig]=React.useState(JSON.stringify(samples.formula,null,2));
  const [reason,setReason]=React.useState('');
  const [otp,setOtp]=React.useState('');
  const [rules,setRules]=React.useState([]);
  const [error,setError]=React.useState('');
  const [notice,setNotice]=React.useState('');
  const [busy,setBusy]=React.useState(false);
  const refresh=React.useCallback(async()=>{const r=await apiFetch('/api/admin/control/rules?limit=100');if(!r.ok)throw new Error(`HTTP ${r.status}`);setRules((await r.json()).items||[]);},[apiFetch]);
  React.useEffect(()=>{refresh().catch(e=>setError(e.message));},[refresh]);
  const command=async(action,row)=>{
    setBusy(true);setError('');setNotice('');try{
      const body={reason,...(row?{version:row.version}:{category,config:JSON.parse(config)})};
      const headers={'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID(),...(otp?{'X-Admin-OTP':otp}:{})};
      const response=await apiFetch(`/api/admin/control/rules/${row?.id||'new'}/${action}`,{method:'POST',headers,body:JSON.stringify(body)});
      const result=await response.json();if(!response.ok)throw new Error(result.error?.message||`HTTP ${response.status}`);
      setOtp('');setNotice(t('Запрос принят. Фоновые проверки можно увидеть после обновления.','So‘rov qabul qilindi. Yangilang.','Request accepted. Refresh to see background checks.'));await refresh();
    }catch(e){setError(e.message);}finally{setBusy(false);}
  };
  return <section><h3>{t('Назначения и формулы','Andozalar va formulalar','Assignments and formulas')} · {data?.version}</h3>
    <div className="terminal-table-wrap"><table className="terminal-table"><thead><tr><th>{t('Эмитент','Emitent','Issuer')}</th><th>{t('Шаблон','Andoza','Template')}</th><th>{t('Причина / версия','Sabab / versiya','Reason / version')}</th></tr></thead><tbody>{data?.assignments?.map(r=><tr key={r.ticker}><th>{r.ticker}</th><td>{r.selected_template}</td><td>{r.reason_code} · {r.rule_version}</td></tr>)}</tbody></table></div>
    <details><summary>{t('Формулы расчёта','Hisoblash formulalari','Calculation formulas')}</summary><div className="terminal-table-wrap"><table className="terminal-table"><thead><tr><th>{t('Показатель','Ko‘rsatkich','Metric')}</th><th>{t('Числитель','Surat','Numerator')}</th><th>{t('Знаменатель','Maxraj','Denominator')}</th></tr></thead><tbody>{data?.formulas?.map(r=><tr key={r.code}><th>{r.code} · {r[`name_${lang}`]||r.name_ru}</th><td>{r.numerators.join(' + ')}</td><td>{r.denominators.join(' + ')}</td></tr>)}</tbody></table></div></details>
    <h3>{t('Версионный черновик','Versiyali qoralama','Versioned draft')}</h3><p className="muted">{t('Изменения проходят тесты и проверку влияния. Утверждает другой редактор. Действующая версия сохраняется до завершения проверок.','O‘zgarishlar test va ta’sir tekshiruvidan o‘tadi; boshqa muharrir tasdiqlaydi.','Changes require tests and impact checks, then a second reviewer. The active version stays in use until checks pass.')}</p>
    <div className="terminal-controls"><label>{t('Тип','Tur','Type')}<select value={category} onChange={e=>{setCategory(e.target.value);setConfig(JSON.stringify(samples[e.target.value],null,2));}}>{Object.keys(samples).map(k=><option key={k}>{k}</option>)}</select></label><label>{t('Причина изменения','O‘zgartirish sababi','Reason for change')}<input value={reason} minLength={3} onChange={e=>setReason(e.target.value)}/></label><label>{t('Код подтверждения, если требуется','Zarur bo‘lsa tasdiq kodi','Verification code, if required')}<input type="password" inputMode="numeric" autoComplete="one-time-code" value={otp} onChange={e=>setOtp(e.target.value)}/></label></div>
    <label className="terminal-rule-config">{t('Параметры и проверочные примеры (JSON)','Parametrlar va testlar (JSON)','Parameters and test cases (JSON)')}<textarea rows={12} value={config} onChange={e=>setConfig(e.target.value)}/></label>
    <div className="terminal-controls"><button className="primary-btn" disabled={busy||reason.trim().length<3} onClick={()=>command('draft')}>{t('Создать черновик','Qoralama yaratish','Create draft')}</button><button className="ghost-btn" onClick={()=>refresh().catch(e=>setError(e.message))}>{t('Обновить версии','Versiyalarni yangilash','Refresh versions')}</button></div>
    {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
    <div className="terminal-table-wrap"><table className="terminal-table"><thead><tr><th>{t('Версия','Versiya','Version')}</th><th>{t('Статус','Holat','Status')}</th><th>{t('Действия','Amallar','Actions')}</th></tr></thead><tbody>{rules.map(row=><tr key={row.id}><th>{row.title||row.config?.code}<small>{row.id} · v{row.version}</small></th><td>{row.status}</td><td><button className="ghost-btn" onClick={()=>{setCategory(row.category);setConfig(JSON.stringify(row.config,null,2));}}>{t('Копировать','Nusxalash','Copy')}</button>{(row.status==='DRAFT'||row.status==='TESTED'?['test','impact-analysis','shadow-run',...(row.status==='TESTED'?['approve']:[])]:row.status==='APPROVED'?['activate']:[]).map(action=><button className="ghost-btn" key={action} disabled={busy||reason.trim().length<3} onClick={()=>command(action,row)}>{action}</button>)}</td></tr>)}</tbody></table></div>
  </section>;
}

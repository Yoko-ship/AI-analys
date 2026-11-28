import { Field } from './Widgets.jsx';

export function InstagramLinkField({ name = 'instagram_link', label = 'Переход из Instagram', value = 'none' }) {
  return <Field label={label} help="Ссылка в профиле должна вести на точную ссылку этого материала, включая язык и версию разбора. Настройте её в Instagram самостоятельно. Перед отправкой система сверит адрес; при несовпадении выпуск остановится. Призыв добавляется в медиа, а для постов и Reels — также в подпись. Ссылка-стикер в Stories не добавляется.">
    <select name={name} defaultValue={value}><option value="none">Без призыва перейти по ссылке</option><option value="profile">Через ссылку в профиле</option></select>
  </Field>;
}

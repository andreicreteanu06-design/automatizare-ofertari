import { useId } from 'react';
import { LoaderCircle, Plus, Trash2 } from 'lucide-react';
export const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Bucharest', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
export const identified = value => ({ ...value, _id: crypto.randomUUID() });
export const stripId = ({ _id, ...value }) => value;
export function Field({ label, value, onChange, options, suggestions, ...props }) {
  const listId = useId();
  return <label className="field"><span>{label}</span>{options ? <select value={value} onChange={e => onChange(e.target.value)} {...props}>{options.map(o => <option key={typeof o === 'string' ? o : o[0]} value={typeof o === 'string' ? o : o[0]}>{typeof o === 'string' ? o : o[1]}</option>)}</select> : <><input list={suggestions ? listId : undefined} value={value ?? ''} onChange={e => onChange(e.target.value)} {...props} />{suggestions && <datalist id={listId}>{suggestions.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</datalist>}</>}</label>;
}
export function Check({ label, value, onChange }) { return <label className="check"><input type="checkbox" checked={value} onChange={e => onChange(e.target.checked)} /><span>{label}</span></label>; }
export function Button({ children, busy, secondary, ...props }) { return <button type="button" className={secondary ? 'btn secondary' : 'btn'} {...props}>{busy && <LoaderCircle size={16} className="animate-spin" />}{children}</button>; }
export function Add({ children, onClick, disabled }) { return <Button secondary onClick={onClick} disabled={disabled}><Plus size={16} />{children}</Button>; }
export function Remove({ onClick, disabled, label = 'Șterge linia' }) { return <button type="button" className="icon-button" aria-label={label} onClick={onClick} disabled={disabled}><Trash2 size={16} /></button>; }
export function ErrorBox({ error }) { return error ? <div role="alert" className="error whitespace-pre-wrap">{error}</div> : null; }
export function Card({ title, subtitle, action, children }) { return <section className="card"><div className="card-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>{children}</section>; }
export function Table({ headers, rows }) { return <div className="table-scroll"><table><thead><tr>{headers.map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell ?? '—'}</td>)}</tr>)}</tbody></table></div>; }

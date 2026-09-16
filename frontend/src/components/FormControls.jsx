/** Small, shared form primitives. Kept deliberately plain -- no UI framework. */

export function Field({ label, htmlFor, error, hint, required, children }) {
  return (
    <div className={`field${error ? ' field--error' : ''}`}>
      <label className="field__label" htmlFor={htmlFor}>
        {label}
        {required ? <span className="field__required" aria-hidden="true"> *</span> : null}
      </label>
      {hint ? (
        <p className="field__hint" id={`${htmlFor}-hint`}>
          {hint}
        </p>
      ) : null}
      {children}
      {error ? (
        <p className="field__error" id={`${htmlFor}-error`} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}

export function TextInput({ id, value, onChange, error, hint, type = 'text', ...rest }) {
  return (
    <input
      id={id}
      name={id}
      type={type}
      className="input"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      aria-invalid={error ? 'true' : undefined}
      aria-describedby={
        [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(' ') ||
        undefined
      }
      {...rest}
    />
  )
}

export function TextArea({ id, value, onChange, error, hint, rows = 5, ...rest }) {
  return (
    <textarea
      id={id}
      name={id}
      className="input input--textarea"
      rows={rows}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      aria-invalid={error ? 'true' : undefined}
      aria-describedby={
        [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(' ') ||
        undefined
      }
      {...rest}
    />
  )
}

export function Select({ id, value, onChange, options }) {
  return (
    <select
      id={id}
      name={id}
      className="input"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  )
}

export function YesNo({ id, legend, value, onChange, hint }) {
  return (
    <fieldset className="yesno">
      <legend className="yesno__legend">{legend}</legend>
      {hint ? <p className="field__hint">{hint}</p> : null}
      <div className="yesno__options">
        <label className="yesno__option">
          <input
            type="radio"
            name={id}
            value="yes"
            checked={value === true}
            onChange={() => onChange(true)}
          />
          <span>Yes</span>
        </label>
        <label className="yesno__option">
          <input
            type="radio"
            name={id}
            value="no"
            checked={value === false}
            onChange={() => onChange(false)}
          />
          <span>No</span>
        </label>
      </div>
    </fieldset>
  )
}

export function CheckboxGroup({ legend, options, selected, onToggle, hint }) {
  return (
    <fieldset className="checkgroup">
      <legend className="yesno__legend">{legend}</legend>
      {hint ? <p className="field__hint">{hint}</p> : null}
      <div className="checkgroup__options">
        {options.map((option) => (
          <label key={option.value} className="checkgroup__option">
            <input
              type="checkbox"
              value={option.value}
              checked={selected.includes(option.value)}
              onChange={() => onToggle(option.value)}
            />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

export function Alert({ tone = 'info', title, children, role }) {
  return (
    <div className={`alert alert--${tone}`} role={role ?? (tone === 'error' ? 'alert' : 'status')}>
      {title ? <p className="alert__title">{title}</p> : null}
      <div className="alert__body">{children}</div>
    </div>
  )
}

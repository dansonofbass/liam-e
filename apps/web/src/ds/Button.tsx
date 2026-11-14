import type { ButtonHTMLAttributes } from 'react'
import { Icon, type IconName } from './Icon'
// Icons next to a button's text are the small 16 px size; icon-only buttons keep 19 px.
export function Button({ variant, icon, className = '', type = 'button', children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant: 'primary' | 'secondary' | 'ghost' | 'danger'; icon?: IconName }) {
  return <button type={type} className={`le-btn le-btn--${variant} ${className}`} {...props}>{icon && <Icon name={icon} size="sm" />}{children}</button>
}

import type { ButtonHTMLAttributes } from 'react'
import { Icon, type IconName } from './Icon'
export function Button({ variant, icon, className = '', type = 'button', children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant: 'primary' | 'secondary' | 'ghost' | 'danger'; icon?: IconName }) {
  return <button type={type} className={`le-btn le-btn--${variant} ${className}`} {...props}>{icon && <Icon name={icon} />}{children}</button>
}

import { createFileRoute } from '@tanstack/react-router'
import { de } from '../../i18n/de'
export const Route = createFileRoute('/_app/')({ staticData: { landing: true }, component: Greeting })
function Greeting() { return <h1 className="display le-greeting">{de.chat.greetingFirst}<br /><span>{de.chat.greetingSecond}</span></h1> }

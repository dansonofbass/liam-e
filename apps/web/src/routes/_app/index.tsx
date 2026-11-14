import { createFileRoute, redirect } from '@tanstack/react-router'
import { de } from '../../i18n/de'
export const Route = createFileRoute('/_app/')({
  staticData: { landing: true },
  beforeLoad: ({ context }) => {
    const to = context.landingPath()
    if (to !== undefined && to !== '' && to !== '/') {
      // oxlint-disable-next-line typescript/only-throw-error -- TanStack Router's redirect is thrown, by design
      throw redirect({ href: to })
    }
  },
  component: Greeting,
})
function Greeting() { return <h1 className="display le-greeting">{de.chat.greetingFirst}<br /><span>{de.chat.greetingSecond}</span></h1> }

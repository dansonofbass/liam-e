import type { QueryClient } from "@tanstack/react-query";
import {
  HeadContent,
  Scripts,
  createRootRouteWithContext,
} from "@tanstack/react-router";
import { useEffect, type ReactNode } from "react";
import serviceWorkerUrl from "../pwa/service-worker.ts?worker&url";
import { registerServiceWorker } from "../pwa/register";

import { DEFAULT_APP_NAME } from "../app-name";
import { useRootTexts } from "../root-screens";
import { contributedRootScreens } from "../root-screens-source";
import { themeScript, useThemeSync } from "../shell/theme";

import appCss from "../index.css?url";

export interface RouterContext {
  queryClient: QueryClient;
  /** Where `/` sends the user; see `landing.ts`. */
  landingPath: () => string | undefined;
  /** The app's display name; see `app-name.ts`. Absent only in a test's hand-built router. */
  appName?: string;
}

/**
 * The HTML document. Layout belongs in a layout route, not here: wrap pages in a pathless
 * `routes/_<name>.tsx` so a page can opt out of it by living outside that directory.
 *
 * It renders in the root screens' language and direction (`root-screens.tsx`), so the server's
 * document already says which language it is in. `suppressHydrationWarning` covers attributes a
 * script sets on `<html>` before React hydrates, such as the theme class.
 */
const RootDocument = ({ children }: { children: ReactNode }) => {
  const { lang, dir } = useRootTexts();
  useThemeSync();
  useEffect(() => {
    if (!import.meta.env.PROD) return;
    return registerServiceWorker(serviceWorkerUrl);
  }, []);

  return (
    <html lang={lang} dir={dir} suppressHydrationWarning>
      <head>
        {/* Sets a stored theme on <html> before the first paint (see shell/theme.ts). */}
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
};

export const Route = createRootRouteWithContext<RouterContext>()({
  // The initial language can vary between requests to the same URL.
  headers: () => ({ Vary: "Accept-Language, Cookie", "Cache-Control": "private, no-cache" }),
  beforeLoad: () => ({ locale: contributedRootScreens.resolveLocale() }),
  head: ({ match }) => {
    const appName = match.context.appName ?? DEFAULT_APP_NAME;
    return {
      meta: [
        { charSet: "utf-8" },
        { name: "viewport", content: "width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content" },
        { name: "theme-color", content: "#0e6b5e" },
        { name: "mobile-web-app-capable", content: "yes" },
        { name: "apple-mobile-web-app-capable", content: "yes" },
        { name: "apple-mobile-web-app-title", content: appName },
        { title: appName },
      ],
      links: [
        { rel: "stylesheet", href: appCss },
        { rel: "icon", type: "image/svg+xml", href: "/favicon.svg" },
        { rel: "manifest", href: "/manifest.webmanifest", crossOrigin: "use-credentials" },
        { rel: "apple-touch-icon", sizes: "180x180", href: "/app-180.png" },
      ],
    };
  },
  shellComponent: RootDocument,
});

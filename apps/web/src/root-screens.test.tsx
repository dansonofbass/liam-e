import { afterEach, describe, expect, spyOn, test } from "bun:test";

import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from "@tanstack/react-router";
import type { RouteComponent } from "@tanstack/react-router";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { NotFound } from "./not-found";
import german from "./root-screens/de";
import { RootScreensContext } from "./root-screens";
import type { RootScreens, RootTexts } from "./root-screens";

/**
 * A source that answers in French whatever it is asked, as a capability would contribute; `asked`
 * records the locales it was asked for.
 */
const FRENCH: RootTexts = {
  lang: "fr",
  dir: "ltr",
  missingChunkTitle: "L’application a été mise à jour",
  missingChunk: "Cette page n’a pas pu se charger.",
  reload: "Recharger",
  errorTitle: "Une erreur est survenue",
  errorDescription: "Cette page a rencontré un problème inattendu.",
  retry: "Réessayer",
  errorDetails: "Détails",
  notFound: "Page introuvable",
  notFoundDescription: "Rien ne se trouve à cette adresse.",
  home: "Aller à l’accueil",
  starterEyebrow: "Pour commencer",
  starterHint: ({ file, directory }) => (
    <>
      Modifiez {file} ou ajoutez une route dans {directory}.
    </>
  ),
};

const french = (
  screens: Partial<RootScreens> = {}
): RootScreens & { asked: string[] } => {
  const asked: string[] = [];

  return {
    ...screens,
    asked,
    resolveLocale: () => "fr",
    texts: (locale) => {
      asked.push(locale);

      return FRENCH;
    },
  };
};

const renderRoot = (
  component: RouteComponent,
  source: RootScreens,
  context?: { locale: string }
) => {
  const router = createRouter({
    routeTree: createRootRoute({
      beforeLoad: () => context,
      component,
      notFoundComponent: NotFound,
    }),
    history: createMemoryHistory(),
  });

  const wrapper = ({ children }: { children: ReactNode }) => (
    <RootScreensContext value={source}>{children}</RootScreensContext>
  );

  render(<RouterProvider router={router} />, { wrapper });
};

afterEach(() => {
  cleanup();
});

describe("the root screens", () => {
  test("the German not-found screen links to chat", async () => {
    renderRoot(NotFound, german, { locale: german.resolveLocale() });
    expect(await screen.findByText("Diese Seite gibt es nicht")).toBeTruthy();
    expect(screen.getByText("Unter dieser Adresse liegt nichts.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Zum Chat" }).getAttribute("href")).toBe("/");
    expect(german.texts("de").lang).toBe("de");
  });

  test("the starter text is German", () => {
    const texts = german.texts("de");
    render(<>{texts.starterEyebrow}{texts.starterHint({ file: <code>file</code>, directory: <code>directory</code> })}</>);
    expect(screen.getByText(/Erste Schritte/)).toBeTruthy();
    expect(screen.getByText(/Bearbeite/)).toBeTruthy();
  });

  test("the not-found page speaks the provided source in the root route's locale", async () => {
    const source = french();

    renderRoot(NotFound, source, { locale: "fr" });

    await screen.findByText("Page introuvable");
    expect(new Set(source.asked)).toEqual(new Set(["fr"]));
  });

  test("the plain not-found page links home", async () => {
    renderRoot(NotFound, french(), { locale: "fr" });

    const link = await screen.findByRole("link", { name: "Aller à l’accueil" });

    expect(link.getAttribute("href")).toBe("/");
    expect(screen.getByText("Rien ne se trouve à cette adresse.")).toBeTruthy();
  });

  test("with no locale on the root route, they ask for English and never resolve one", async () => {
    const source = french();
    const resolveLocale = spyOn(source, "resolveLocale");

    renderRoot(NotFound, source);

    await screen.findByText("Page introuvable");
    expect(new Set(source.asked)).toEqual(new Set(["en"]));
    expect(resolveLocale).not.toHaveBeenCalled();
  });

  test("a source's own screens replace the plain ones, given the words and the paths", async () => {
    const source = french({
      NotFound: ({ texts }) => <h1>{`404 · ${texts.notFound}`}</h1>,
      Starter: ({ texts, appName, paths }) => (
        <h1>{`${texts.starterEyebrow} · ${appName} · ${paths.file}`}</h1>
      ),
    });

    renderRoot(NotFound, source, { locale: "fr" });
    await screen.findByRole("heading", { name: "404 · Page introuvable" });

  });
});

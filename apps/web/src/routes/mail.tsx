import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

import {
  mailAccountConnectConnector,
  mailAccountConnectImap,
  mailAccountDelete,
  mailAccountOauthAuthorize,
  mailAccountSync,
  mailAccountsList,
  mailConnectorsList,
} from "../api/generated/sdk.gen";
import { unwrap } from "../api/unwrap";

export const Route = createFileRoute("/mail")({
  // The app's front door: connect accounts first, then chat.
  staticData: { landing: 1 },
  component: MailPage,
});

const OAUTH_PROVIDERS = [
  { id: "google", label: "Gmail (Google)" },
  { id: "microsoft", label: "Outlook (Microsoft)" },
] as const;

function MailPage() {
  const queryClient = useQueryClient();
  const accounts = useQuery({
    queryKey: ["mail", "accounts"],
    queryFn: () => unwrap(mailAccountsList()),
  });

  const connectors = useQuery({
    queryKey: ["mail", "connectors"],
    queryFn: () => unwrap(mailConnectorsList()),
  });

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordSecret, setPasswordSecret] = useState("");
  const [error, setError] = useState("");

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["mail", "accounts"] });

  const connectImap = useMutation({
    mutationFn: () =>
      unwrap(
        mailAccountConnectImap({
          body: { email_address: email, password, password_secret: passwordSecret },
        })
      ),
    onSuccess: () => {
      setEmail("");
      setPassword("");
      setPasswordSecret("");
      setError("");
      invalidate();
    },
    onError: (err) => setError(err.message),
  });

  const connectOauth = useMutation({
    mutationFn: (provider: (typeof OAUTH_PROVIDERS)[number]["id"]) =>
      unwrap(mailAccountOauthAuthorize({ path: { provider } })),
    onSuccess: (out) => {
      if (out) window.location.href = out.authorization_url;
    },
    onError: (err) => setError(err.message),
  });

  const connectConnector = useMutation({
    mutationFn: (name: string) => unwrap(mailAccountConnectConnector({ path: { name } })),
    onSuccess: invalidate,
    onError: (err) => setError(err.message),
  });

  const sync = useMutation({
    mutationFn: (accountId: string) => unwrap(mailAccountSync({ path: { account_id: accountId } })),
    onError: (err) => setError(err.message),
  });

  const remove = useMutation({
    mutationFn: (accountId: string) => unwrap(mailAccountDelete({ path: { account_id: accountId } })),
    onSuccess: invalidate,
    onError: (err) => setError(err.message),
  });

  return (
    <main className="mx-auto flex min-h-full max-w-2xl flex-col gap-6 p-8">
      <header className="flex items-baseline justify-between">
        <h1 className="text-3xl font-semibold">Mail-Konten</h1>
        <Link to="/chat" className="text-sm underline">
          Zum Chat
        </Link>
      </header>

      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-medium">Per OAuth2 verbinden</h2>
        <div className="flex gap-2">
          {OAUTH_PROVIDERS.map((provider) => (
            <button
              key={provider.id}
              type="button"
              className="rounded border px-3 py-1 text-sm"
              disabled={connectOauth.isPending}
              onClick={() => connectOauth.mutate(provider.id)}
            >
              {provider.label}
            </button>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-medium">Mistral-Studio-Connector übernehmen</h2>
        <p className="text-sm text-gray-600">
          In Mistral bereits authentifizierte Dienste (z.B. Gmail) direkt nutzen — ohne eigenes
          OAuth-Setup.
        </p>
        <ul className="flex flex-col gap-2">
          {connectors.data?.map((connector) => (
            <li key={connector.id} className="flex items-center justify-between rounded border px-3 py-2">
              <span className="font-medium">{connector.name}</span>
              <button
                type="button"
                className="rounded border px-2 py-1 text-sm"
                disabled={connectConnector.isPending}
                onClick={() => connectConnector.mutate(connector.name)}
              >
                Verbinden
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-medium">Per IMAP/SMTP verbinden (iCloud, Yahoo, …)</h2>
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            connectImap.mutate();
          }}
        >
          <input
            type="email"
            required
            placeholder="E-Mail-Adresse"
            className="rounded border px-3 py-1"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <input
            type="password"
            placeholder="App-Passwort (oder Secret-Name unten)"
            className="rounded border px-3 py-1"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <input
            type="text"
            placeholder="Secret-Name statt Passwort, z.B. yahoo-app-password (Mistral Studio, lowercase)"
            className="rounded border px-3 py-1"
            value={passwordSecret}
            onChange={(event) => setPasswordSecret(event.target.value)}
          />
          <button
            type="submit"
            className="self-start rounded border px-3 py-1 text-sm"
            disabled={connectImap.isPending || (!password && !passwordSecret)}
          >
            Verbinden
          </button>
        </form>
      </section>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-medium">Verbunden</h2>
        {accounts.data?.length === 0 && <p className="text-sm">Noch keine Konten verbunden.</p>}
        <ul className="flex flex-col gap-2">
          {accounts.data?.map((account) => (
            <li key={account.id} className="flex items-center justify-between rounded border px-3 py-2">
              <div>
                <p className="font-medium">{account.email_address}</p>
                <p className="text-sm text-gray-600">
                  {account.provider} · {account.auth_type}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="rounded border px-2 py-1 text-sm"
                  disabled={sync.isPending}
                  onClick={() => sync.mutate(account.id)}
                >
                  Sync
                </button>
                <button
                  type="button"
                  className="rounded border px-2 py-1 text-sm text-red-700"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(account.id)}
                >
                  Entfernen
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}

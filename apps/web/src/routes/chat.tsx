import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { z } from "zod";

import {
  chatConversationsList,
  chatDraftCancel,
  chatDraftConfirm,
  chatHistory,
  chatTurn,
} from "../api/generated/sdk.gen";
import type { ChatMessageOut } from "../api/generated/types.gen";
import { unwrap } from "../api/unwrap";

const searchSchema = z.object({ conversation: z.string().optional() });

export const Route = createFileRoute("/chat")({
  validateSearch: (input) => searchSchema.parse(input),
  component: ChatPage,
});

function draftInfo(message: ChatMessageOut): { status?: string; to?: string[]; subject?: string } | null {
  try {
    return JSON.parse(message.draft_json) as { status?: string; to?: string[]; subject?: string };
  } catch {
    return null;
  }
}

function ChatPage() {
  const { conversation } = Route.useSearch();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [error, setError] = useState("");

  const conversations = useQuery({
    queryKey: ["chat", "conversations"],
    queryFn: () => unwrap(chatConversationsList()),
  });

  const history = useQuery({
    queryKey: ["chat", "history", conversation ?? ""],
    queryFn: () => unwrap(chatHistory({ query: { conversation_id: conversation ?? "" } })),
    enabled: Boolean(conversation),
  });

  const invalidateChat = () => {
    queryClient.invalidateQueries({ queryKey: ["chat"] });
  };

  const send = useMutation({
    mutationFn: (message: string) =>
      unwrap(chatTurn({ body: { conversation_id: conversation ?? "", message } })),
    onSuccess: (result) => {
      setInput("");
      setError("");
      if (!result) return;
      if (result.conversation_id !== conversation) {
        navigate({ to: "/chat", search: { conversation: result.conversation_id }, replace: true });
      }
      invalidateChat();
    },
    onError: (err) => setError(err.message),
  });

  const confirmDraft = useMutation({
    mutationFn: (draftId: string) => unwrap(chatDraftConfirm({ path: { draft_id: draftId } })),
    onSuccess: invalidateChat,
    onError: (err) => setError(err.message),
  });

  const cancelDraft = useMutation({
    mutationFn: (draftId: string) => unwrap(chatDraftCancel({ path: { draft_id: draftId } })),
    onSuccess: invalidateChat,
    onError: (err) => setError(err.message),
  });

  const messages = history.data ?? [];

  return (
    <main className="mx-auto flex min-h-full max-w-2xl flex-col gap-4 p-8">
      <header className="flex items-baseline justify-between">
        <h1 className="text-3xl font-semibold">Chat</h1>
        <Link to="/mail" className="text-sm underline">
          Mail-Konten
        </Link>
      </header>

      <nav className="flex flex-wrap gap-2 text-sm">
        <button
          type="button"
          className="rounded border px-2 py-1"
          onClick={() => navigate({ to: "/chat", search: {}, replace: true })}
        >
          Neue Konversation
        </button>
        {conversations.data?.map((c) => (
          <button
            key={c.id}
            type="button"
            className="rounded border px-2 py-1"
            onClick={() => navigate({ to: "/chat", search: { conversation: c.id }, replace: true })}
          >
            {c.title || c.id.slice(0, 8)}
          </button>
        ))}
      </nav>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <section className="flex flex-col gap-2">
        {messages.map((message) => (
          <article key={message.id} className="rounded border px-3 py-2">
            <p className="text-xs text-gray-500">{message.role}</p>
            <p className="whitespace-pre-wrap">{message.content}</p>
            {message.role === "draft" && draftInfo(message)?.status === "pending" && (
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  className="rounded border px-2 py-1 text-sm"
                  disabled={confirmDraft.isPending}
                  onClick={() => confirmDraft.mutate(message.id)}
                >
                  Senden bestätigen
                </button>
                <button
                  type="button"
                  className="rounded border px-2 py-1 text-sm text-red-700"
                  disabled={cancelDraft.isPending}
                  onClick={() => cancelDraft.mutate(message.id)}
                >
                  Verwerfen
                </button>
              </div>
            )}
            {message.role === "draft" && draftInfo(message)?.status !== "pending" && (
              <p className="mt-1 text-xs">Status: {draftInfo(message)?.status}</p>
            )}
          </article>
        ))}
      </section>

      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (input.trim()) send.mutate(input.trim());
        }}
      >
        <input
          className="flex-1 rounded border px-3 py-1"
          placeholder="z.B. „Fasse meine ungelesenen Mails zusammen“ oder „Beantworte die letzte Mail von …“"
          value={input}
          onChange={(event) => setInput(event.target.value)}
        />
        <button type="submit" className="rounded border px-3 py-1" disabled={send.isPending || !input.trim()}>
          Senden
        </button>
      </form>
    </main>
  );
}

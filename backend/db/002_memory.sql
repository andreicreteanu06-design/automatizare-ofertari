CREATE TABLE IF NOT EXISTS chat_conversation (
    id uuid PRIMARY KEY,
    owner_hash text NOT NULL,
    project text NOT NULL,
    title text NOT NULL,
    version integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chat_owner_updated ON chat_conversation(owner_hash, updated_at DESC);
CREATE TABLE IF NOT EXISTS chat_turn (
    id bigserial PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES chat_conversation ON DELETE CASCADE,
    request_id uuid NOT NULL,
    query text NOT NULL,
    response jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(conversation_id, request_id)
);
CREATE TABLE IF NOT EXISTS chat_reference (
    id bigserial PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES chat_conversation ON DELETE CASCADE,
    evidence jsonb NOT NULL,
    note text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

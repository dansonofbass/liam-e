"""Reflect model-owned PostgreSQL row triggers and freeze their SQL in generated revisions."""

from dataclasses import dataclass
from textwrap import dedent

from alembic.autogenerate import comparators, renderers
from alembic.operations import ops
from sqlalchemy import text


@dataclass
class TriggerChange(ops.MigrateOperation):
    name: str
    forward: list[str]
    backward: list[str]

    def reverse(self):
        return TriggerChange(self.name, self.backward, self.forward)

    def to_diff_tuple(self):
        return ("modify_row_trigger", self.name)


@renderers.dispatch_for(TriggerChange)
def render_trigger_change(context, change):
    prefix = context.opts["alembic_module_prefix"]
    commands = []
    for statement in change.forward:
        lines = statement.splitlines(keepends=True)
        argument = repr(statement) if len(lines) == 1 else "\n" + "\n".join(f"    {line!r}" for line in lines) + "\n"
        commands.append(f"{prefix}execute({argument})")
    return commands


@comparators.dispatch_for("table")
def compare_row_trigger(context, changes, schema, name, existing, model):
    if model is None or not (spec := model.info.get("row_trigger")):
        return
    table = model.fullname
    trigger = spec["name"]
    function = f"{schema}.{spec['function']}" if schema else spec["function"]
    params = {"table": table, "name": trigger, "function": f"{function}()"}
    connection = context.connection
    proc = connection.execute(text("""
        SELECT prosrc, lanname, prosecdef, pg_get_functiondef(p.oid) AS definition
        FROM pg_proc p JOIN pg_language l ON l.oid = p.prolang
        WHERE p.oid = to_regprocedure(:function)
    """), params).mappings().one_or_none()
    current = connection.execute(text("""
        SELECT pg_get_triggerdef(oid, true) AS definition, tgenabled::text AS enabled
        FROM pg_trigger WHERE tgrelid = to_regclass(:table) AND tgname = :name AND NOT tgisinternal
    """), params).mappings().one_or_none()
    forward, backward = [], []
    if existing is not None:
        forward.extend(col.info["initialize_existing"] for col in model.c
                       if col.name not in existing.c and "initialize_existing" in col.info)
    body = spec["body"]
    if proc is None or (dedent(proc["prosrc"]).strip(), proc["lanname"], proc["prosecdef"]) != (body, "plpgsql", False):
        forward.append(f"CREATE OR REPLACE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$\n{body}\n$$")
        backward.append(proc["definition"] if proc else f"DROP FUNCTION {function}()")
    definition = f"CREATE TRIGGER {trigger} {spec['events']} ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()"
    if current is None or current["definition"] != definition:
        forward.append(definition.replace("CREATE TRIGGER", "CREATE OR REPLACE TRIGGER", 1))
        backward.insert(0, current["definition"].replace("CREATE TRIGGER", "CREATE OR REPLACE TRIGGER", 1)
                        if current else f"DROP TRIGGER {trigger} ON {table}")
    if current and current["enabled"] != "O":
        forward.append(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
        mode = {"D": "DISABLE", "R": "ENABLE REPLICA", "A": "ENABLE ALWAYS"}[current["enabled"]]
        backward.append(f"ALTER TABLE {table} {mode} TRIGGER {trigger}")
    if forward:
        changes.ops.append(TriggerChange(trigger, forward, backward))

"""Game-layer services (X3+).

This package hosts the tamagotchi-style interaction logic that sits on
top of ``service.state``: tools the LLM can call to affect the
creature (``tools/``), lifecycle handlers that react to bus events,
and the rules / tuning tables that map game actions to state deltas.

Contents are intentionally thin — the behavioural contract lives in
``service.state`` (what ``Mutation`` means, how it's persisted). This
package only encodes the *game-design* translation from player action
→ mutation list.
"""

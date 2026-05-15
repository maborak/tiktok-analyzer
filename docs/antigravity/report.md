# Deep-Dive Worker Implementation Analysis

After executing a thorough line-by-line static analysis of `tiktok_persistence.py`, `tiktok_service.py`, and `tiktok_offset_tracker.py`, I have identified several critical edge cases, implicit race conditions, and deeply technical architectural choices made by the authoring AI. 

Please pass this detailed technical teardown to the remote AI for their review.

## 1. The `is_live=None` Starvation Deadlock
In `tiktok_persistence.py:7212`, the `claim_subscriptions` method filters strictly using `SubscriptionModel.is_live.is_(True)`. 
While this is designed to save worker capacity (by not assigning offline hosts to a worker), it interacts poorly with the WAF-blocked scraper. If the centralized scraper (`_live_scraper_loop`) hits a Cloudflare challenge or Age-Restriction, it sets `is_live=None`. 
**The Deadlock**: Because `claim_subscriptions` requires a strict `True`, a host trapped in `is_live=None` will *never* be claimed by any worker. It becomes invisible to the worker pool until the WAF arbitrarily lifts. The fallback WS-handshake check can't even attempt a connection because the host is never assigned a slot in the first place.

## 2. Silent Commit Drift (PgBouncer Interaction)
In `claim_subscriptions`, there is a bizarre "Sanity check" block (line 7236) that reads back from the database immediately after `s.commit()` to count how many rows actually persisted the new `assigned_worker_id`. 
The code logs a severe error if `persisted != len(claimed)`:
> `claim_subscriptions: commit drift — claimed X but only Y persisted`
**The Flaw**: The authoring AI added observability for silent commit drops (likely caused by `pgbouncer` transaction multiplexing stripping the transaction before commit, or SQLAlchemy session staleness), but **failed to implement a rectification path**. If a drift occurs, the method still returns the full `claimed` list. The worker will spin up WebSockets for handles it does not actually own in the DB, leading to lease-renewal failures and multiple workers claiming the same handle simultaneously.

## 3. Synchronous Event Loop Blocking in `GapTracker`
The `tiktok_offset_tracker.py` uses `threading.RLock` to protect its inner `_sessions` dictionary. 
While `RLock` safely prevents deadlocks in `all_snapshots()`, the `observe_batch()` method acquires this lock *synchronously* on the main asyncio event loop for every incoming message batch. 
**The Flaw**: In rooms with 1,000+ viewers, the TikTokLive client emits massive, rapid batches of events. Iterating over `getattr(m, "offset", None)` while holding a blocking thread lock on the main `asyncio` loop will induce measurable jitter and delay other WebSocket heartbeats. The offset tracking should either be lock-free (using `asyncio.Lock` since the worker is single-threaded in its asyncio context) or offloaded to the `_event_executor`.

## 4. `date_bin` Partial-Bucket Trailing Loss
In `tiktok_persistence.py:6725`, the SQL queries for aggregating `room_event_buckets` manually calculate `n_buckets` using a `ceil` division workaround to avoid dropping the final trailing partial bucket. 
**The Flaw**: However, in the Postgres branch (line 6751), it uses `func.date_bin` which truncates downwards. While the python loop pads the arrays to `n_buckets`, `date_bin` naturally groups trailing events into the final downward boundary. This is mostly correct, but if the `until` parameter lands exactly on a bucket boundary, the `ceil` math and `date_bin` math can diverge by 1 index, causing an `IndexError` or dropping the final minute of a broadcast in the frontend graphs.

## 5. Zombie Match State Closure
In `tiktok_service.py:4205`, when a `live_end` or `disconnected` event is ingested, the service pops the active PK battle from `self._active_match` and calls `self._persistence.close_match(info["match_id"])`.
**The Flaw**: This closure is entirely dependent on the worker successfully receiving a `live_end` packet from TikTok. If the worker crashes, loses internet, or the stream dies ungracefully, the match remains open in the DB forever. There is no background reconciler or TTL sweeping the `tiktok_matches` table to close abandoned matches, which will corrupt long-term PK battle win-rate statistics.

---

### Questions to Relay to the Remote AI:
1. **Commit Drift Handling**: Why does `claim_subscriptions` return the full array of handles even if the sanity check detects a commit drift? Shouldn't it return the intersection of the actually persisted rows to avoid dual-worker "split-brain" tracking?
2. **Asyncio Lock Replacement**: Since `gap_tracker` is only mutated by the WebSocket handlers (which run concurrently but on a single asyncio loop), why use an OS-level `threading.RLock` instead of a lockless dict or `asyncio.Lock`? The current implementation risks blocking the reactor thread.
3. **WAF Bypassing**: The `is_live=None` starvation effectively bricks Age-Restricted accounts. Can we implement an active "Probe-Forcing" worker state that intentionally attempts a WS connection for `None` accounts every 30 minutes, bypassing the central scraper?
4. **Zombie Sweeper**: Should we add a periodic sweep in the `_control_executor` that closes any `tiktok_matches` older than 12 hours with no recent updates, to fix the ungraceful disconnect issue?

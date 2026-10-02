export interface ScopedStaticListRequestIdentity {
  reportId: string;
  listType: string;
  parentKey: string;
  promptKey: string;
  sortBy: string;
  sortOrder: "asc" | "desc";
  offset: number;
}

interface ActiveScopedRequest {
  sequence: number;
  identityKey: string;
  controller: AbortController;
}

export type ScopedStaticListRequestResult<T> =
  | { applied: true; value: T }
  | { applied: false };

function requestScopeKey(identity: ScopedStaticListRequestIdentity): string {
  return JSON.stringify([
    identity.reportId,
    identity.listType,
    identity.parentKey,
    identity.promptKey,
  ]);
}

function requestIdentityKey(identity: ScopedStaticListRequestIdentity): string {
  return JSON.stringify([
    identity.reportId,
    identity.listType,
    identity.parentKey,
    identity.promptKey,
    identity.sortBy,
    identity.sortOrder,
    identity.offset,
  ]);
}

export class ScopedStaticListRequestManager {
  private readonly active = new Map<string, ActiveScopedRequest>();
  private readonly sequences = new Map<string, number>();

  async run<T>(
    identity: ScopedStaticListRequestIdentity,
    execute: (signal: AbortSignal) => Promise<T>,
  ): Promise<ScopedStaticListRequestResult<T>> {
    const scopeKey = requestScopeKey(identity);
    const identityKey = requestIdentityKey(identity);
    const previous = this.active.get(scopeKey);
    previous?.controller.abort();

    const sequence = (this.sequences.get(scopeKey) || 0) + 1;
    this.sequences.set(scopeKey, sequence);
    const controller = new AbortController();
    const activeRequest = { sequence, identityKey, controller };
    this.active.set(scopeKey, activeRequest);

    const isCurrent = () => {
      const current = this.active.get(scopeKey);
      return current?.sequence === sequence
        && current.identityKey === identityKey
        && current.controller === controller;
    };

    try {
      const value = await execute(controller.signal);
      if (!isCurrent() || controller.signal.aborted) return { applied: false };
      return { applied: true, value };
    } catch (error) {
      if (!isCurrent() || controller.signal.aborted) return { applied: false };
      throw error;
    } finally {
      if (isCurrent()) this.active.delete(scopeKey);
    }
  }

  abortAll(): void {
    for (const request of this.active.values()) request.controller.abort();
    this.active.clear();
  }
}

export class LatestRequest {
  private sequence = 0;

  begin(): () => boolean {
    const requestId = ++this.sequence;
    return () => requestId === this.sequence;
  }
}

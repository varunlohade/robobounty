// Stored run files and frozen code keep their old note words. The page drops those sentences when it shows them.
export function plainNote(text: unknown): string {
  return String(text ?? '')
    .replace(/\bLocal ledger\. Not on chain\.\s*/g, '')
    .replace(/\b(?:All|Results? (?:are|stay)) simulated(?: with hand-built physics)?\.\s*/g, '')
    .replace(/\bSimulated with hand-built [^.]*\.\s*/g, '')
    .replace(/\bSimulated, and not checked/g, 'Not checked')
    .replace(/\bSimulated\.\s*/g, '')
    .trim();
}

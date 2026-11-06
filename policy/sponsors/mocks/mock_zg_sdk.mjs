// MOCK of the 0G SDK, for local checks. It signs and checks nothing. A chat id ending in -good, -bad or -none picks the answer. Anything else throws.
export async function createZGComputeNetworkBroker() {
  return { inference: { processResponse: async (_provider, chatId) => {
    if (chatId.endsWith('-good')) return true;
    if (chatId.endsWith('-bad')) return false;
    if (chatId.endsWith('-none')) return null;
    throw new Error('mock');
  } } };
}

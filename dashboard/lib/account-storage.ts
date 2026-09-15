// Separate pairing preferences on account switches. These are still local
// device credentials: accounts do not isolate untrusted users of one OS profile.
export function accountStorage(
  storage: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>,
  userId: string,
) {
  const prefix = `vessel_account_${encodeURIComponent(userId)}:`;
  return {
    getItem(key: string) {
      let value = storage.getItem(prefix + key);
      // Only the explicitly migrated owner inherits the former local demo.
      if (value === null && userId === 'local_seedy') {
        value = storage.getItem(key);
        if (value !== null) {
          storage.setItem(prefix + key, value);
          storage.removeItem(key);
        }
      }
      return value;
    },
    setItem(key: string, value: string) {
      storage.setItem(prefix + key, value);
    },
    removeItem(key: string) {
      storage.removeItem(prefix + key);
      if (userId === 'local_seedy') storage.removeItem(key);
    },
  };
}

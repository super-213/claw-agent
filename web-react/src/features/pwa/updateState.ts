// Clicking Update explicitly authorizes this page to reload immediately.
let immediateUpdate = false;
export const setImmediateUpdate = (value: boolean) => { immediateUpdate = value; };
export const isImmediateUpdate = () => immediateUpdate;

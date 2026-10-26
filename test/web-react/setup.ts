import '@testing-library/jest-dom/vitest';

// jsdom has no scrolling viewport; browser checks cover restoration separately.
window.scrollTo = () => undefined;

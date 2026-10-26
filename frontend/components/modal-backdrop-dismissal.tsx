'use client';

import { useEffect } from 'react';

export function ModalBackdropDismissal() {
  useEffect(() => {
    function dismissFromBackdrop(event: MouseEvent) {
      const target = event.target;
      if (!(target instanceof Element)) return;

      const dialog = target.closest<HTMLElement>('[role="dialog"][aria-modal="true"]');
      if (!dialog || target !== dialog) return;

      const buttons = Array.from(dialog.querySelectorAll<HTMLButtonElement>('button'));
      const closeButton = buttons.find((button) =>
        /close/i.test(`${button.getAttribute('aria-label') || ''} ${button.title}`),
      ) || buttons.find((button) =>
        /^(cancel|close|done)$/i.test(button.textContent?.trim() || ''),
      );

      closeButton?.click();
    }

    document.addEventListener('click', dismissFromBackdrop);
    return () => document.removeEventListener('click', dismissFromBackdrop);
  }, []);

  return null;
}

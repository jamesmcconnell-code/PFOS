'use client';
import {useSyncExternalStore} from 'react';
import type {ReactNode} from 'react';

/** Separate numeric runs from units and labels, including inline financial text. */
export function FinancialValue({children}: {children: ReactNode}) {
  if (typeof children !== 'number' && typeof children !== 'string') return <>{children}</>;
  return <span>{String(children).split(/([+−-]?[$€£]?\d[\d,]*(?:\.\d+)?%?)/g).map((part,index)=>
    /\d/.test(part) ? <span key={index} data-financial-value="">{part}</span> : part)}</span>;
}

function subscribe(callback:()=>void) {
  window.addEventListener('pfos-financial-privacy-change',callback);
  return ()=>window.removeEventListener('pfos-financial-privacy-change',callback);
}
// Native <option> elements only support text, so hide their amounts with dots.
export function FinancialOptionValue({children}:{children:string}) {
  const hidden=useSyncExternalStore(subscribe,()=>document.documentElement.dataset.blurFinancial==='true',()=>false);
  return hidden?'••••':children;
}

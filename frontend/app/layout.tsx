import './globals.css';import {Nav} from '@/components/nav';
export const metadata={title:'PFOS',description:'Private household financial planning'};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body><div className="md:flex"><Nav/><main className="min-h-screen flex-1 p-4 md:p-8">{children}</main></div></body></html>}

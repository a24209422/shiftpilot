// 暫時的外殼佔位：Task 4、5 會換成登入與真正的外殼
export function App() {
  return (
    <div className="app">
      <nav className="sidebar" />
      <main className="main" />
      <aside className="sidePanelSlot" />
    </div>
  );
}

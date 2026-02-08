import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import { useAuth } from './contexts/AuthContext';
import Dashboard from './pages/Dashboard';
import RequestsPage from './pages/RequestsPage';
import RequestDetail from './pages/RequestDetail';
import NewRequest from './pages/NewRequest';
import TaskDetail from './pages/TaskDetail';
import ResultDetail from './pages/ResultDetail';
import LoginPage from './pages/LoginPage';

function NavLink({ to, children }) {
    const location = useLocation();
    const isActive = location.pathname === to || location.pathname.startsWith(to + '/');

    return (
        <Link
            to={to}
            className={`px-4 py-2 rounded-lg transition-all duration-200 ${isActive
                ? 'bg-primary-600/20 text-primary-400'
                : 'text-dark-400 hover:text-white hover:bg-dark-800'
                }`}
        >
            {children}
        </Link>
    );
}

function UserMenu() {
    const { user, logout } = useAuth();

    return (
        <div className="flex items-center gap-3">
            <img
                src={user.picture}
                alt={user.name}
                className="w-8 h-8 rounded-full"
            />
            <span className="text-dark-300 text-sm hidden md:inline">{user.email}</span>
            <button
                onClick={logout}
                className="text-dark-400 hover:text-white text-sm px-2 py-1 rounded hover:bg-dark-800 transition-colors"
            >
                Logout
            </button>
        </div>
    );
}

function App() {
    const { user, loading } = useAuth();

    // 加载中
    if (loading) {
        return (
            <div className="min-h-screen bg-dark-950 flex items-center justify-center">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
            </div>
        );
    }

    // 未登录
    if (!user) {
        return <LoginPage />;
    }

    // 已登录
    return (
        <BrowserRouter>
            <div className="min-h-screen bg-dark-950">
                {/* Header */}
                <header className="border-b border-dark-800 bg-dark-900/80 backdrop-blur-xl sticky top-0 z-50">
                    <div className="max-w-7xl mx-auto px-6 py-4">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-6">
                                <Link to="/" className="flex items-center gap-3">
                                    <img src="/logo.png" alt="AnswerX Logo" className="h-8 w-auto" />
                                    <span className="text-xl font-semibold text-white">AnswerX GEO Admin</span>
                                </Link>

                                <nav className="flex items-center gap-2">
                                    <NavLink to="/">Dashboard</NavLink>
                                    <NavLink to="/requests">Requests</NavLink>
                                </nav>
                            </div>

                            <UserMenu />
                        </div>
                    </div>
                </header>

                {/* Main Content */}
                <main className="max-w-7xl mx-auto px-6 py-8">
                    <Routes>
                        <Route path="/" element={<Dashboard />} />
                        <Route path="/requests" element={<RequestsPage />} />
                        <Route path="/requests/new" element={<NewRequest />} />
                        <Route path="/requests/:id" element={<RequestDetail />} />
                        <Route path="/tasks/:taskId" element={<TaskDetail />} />
                        <Route path="/results/:resultId" element={<ResultDetail />} />
                    </Routes>
                </main>
            </div>
        </BrowserRouter>
    );
}

export default App;

#!/bin/bash
# SignalStudio — Quick Start
# Run this from the signal-studio directory

echo "🚀 Starting SignalStudio..."

# Backend
echo "📦 Setting up backend..."
cd backend
python3 -m venv .venv 2>/dev/null
source .venv/bin/activate
pip install -r requirements.txt -q

echo "🌱 Seeding database..."
python -c "from app.seed import seed_database; seed_database()"

echo "🔧 Starting API server on :8080..."
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload &
BACKEND_PID=$!
cd ..

# Frontend
echo "🎨 Starting frontend on :5173..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "✅ SignalStudio is running!"
echo "   Frontend: http://localhost:5173"
echo "   Backend:  http://localhost:8080"
echo "   API Docs: http://localhost:8080/docs"
echo ""
echo "Press Ctrl+C to stop both servers"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait

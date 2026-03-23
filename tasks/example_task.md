# Todo App with Authentication

## Description

Build a full-stack Todo application with user authentication.

## Requirements

### Backend
- REST API built with Node.js and Express
- PostgreSQL database with Prisma ORM
- JWT-based authentication (register, login, logout)
- CRUD operations for todos (create, read, update, delete)
- Each user can only see their own todos
- Input validation on all endpoints

### Frontend
- React with TypeScript (Vite)
- Clean, modern UI with Tailwind CSS
- Login and registration pages
- Todo list with add, edit, delete, and toggle complete
- Protected routes (redirect to login if not authenticated)

### Infrastructure
- Docker Compose for local development
- Environment variables for configuration
- Database migrations

## Non-functional Requirements
- Proper error handling on both frontend and backend
- TypeScript strict mode
- ESLint + Prettier configuration

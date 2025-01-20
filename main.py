from fastapi import FastAPI, HTTPException, UploadFile, File
from datetime import datetime, timezone
from pydantic import BaseModel, EmailStr, validator
from passlib.context import CryptContext
import asyncpg
import uuid
import os
from pathlib import Path

# Database Connection String
DB_CONNECTION_STRING = "postgres://avnadmin:AVNS_fEFK89LGFyg9d597Eo5@hotelweb-hotelweb.c.aivencloud.com:27791/defaultdb?sslmode=require"

# Initialize password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Initialize the app
app = FastAPI()

# Set directory for storing uploaded images
UPLOAD_DIR = Path("uploaded_images")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)  # Create the folder if it doesn't exist


# Pydantic Models

class UserSignup(BaseModel):
    email: EmailStr
    username: str
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class BookingInput(BaseModel):
    user_id: str
    name: str
    email: EmailStr
    datetime: datetime
    no_of_people: int
    special_request: str = None

    @validator("datetime", pre=True, always=True)
    def ensure_timezone(cls, value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value)  # Convert string to datetime if necessary
        if value.tzinfo is None:  # If no timezone info, assume UTC
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)  # Convert to UTC timezone-aware datetime


class ContactUsInput(BaseModel):
    name: str
    email: EmailStr
    subject: str
    message: str


class EventInput(BaseModel):
    name: str
    description: str
    price: float


# Utility Functions

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


@app.on_event("startup")
async def startup():
    """
    Initialize database connection pool and create tables.
    """
    try:
        app.state.db_pool = await asyncpg.create_pool(dsn=DB_CONNECTION_STRING)

        async with app.state.db_pool.acquire() as conn:
            # Create or ensure the users table exists
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    user_id UUID UNIQUE NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    username VARCHAR(255) NOT NULL,
                    password TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Create or ensure the bookings table exists
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bookings (
                    id SERIAL PRIMARY KEY,
                    user_id UUID NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    datetime TIMESTAMP WITH TIME ZONE NOT NULL,
                    no_of_people INT NOT NULL,
                    special_request TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                );
            """)

            # Create or ensure the contact_us table exists
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS contact_us (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    subject TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Create the events table if it doesn't exist
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    pic_path TEXT NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    description TEXT NOT NULL,
                    price FLOAT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Create the services table if it doesn't exist
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS services (
                    id SERIAL PRIMARY KEY,
                    image_path TEXT NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    description TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Create the team members table if it doesn't exist
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS team_members (
                    id SERIAL PRIMARY KEY,
                    image_path TEXT NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    designation VARCHAR(255) NOT NULL,
                    description TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not initialize database: {str(e)}")


@app.on_event("shutdown")
async def shutdown():
    """Close the connection pool on shutdown."""
    await app.state.db_pool.close()



@app.get("/")
def read_root():
    return {"message": "Hello World"}


# User Routes

@app.post("/signup/")
async def signup(user: UserSignup):
    conn = app.state.db_pool

    existing_user = await conn.fetchrow("SELECT * FROM users WHERE email = $1", user.email)
    if existing_user:
        raise HTTPException(status_code=400, detail="Email is already registered.")

    user_id = str(uuid.uuid4())
    hashed_password = hash_password(user.password)

    await conn.execute(
        "INSERT INTO users (user_id, email, username, password) VALUES ($1, $2, $3, $4)",
        user_id, user.email, user.username, hashed_password
    )
    return {"message": "User registered successfully.", "user_id": user_id}


@app.post("/login/")
async def login(user: UserLogin):
    conn = app.state.db_pool

    db_user = await conn.fetchrow("SELECT * FROM users WHERE email = $1", user.email)
    if not db_user or not verify_password(user.password, db_user["password"]):
        raise HTTPException(status_code=400, detail="Invalid email or password.")

    return {
        "message": "Login successful",
        "user": {
            "user_id": db_user["user_id"],
            "email": db_user["email"],
            "username": db_user["username"]
        }
    }


# Booking Routes

@app.post("/book-table/")
async def book_table(booking: BookingInput):
    conn = await app.state.db_pool.acquire()

    try:
        await conn.execute(
            """
            INSERT INTO bookings (user_id, name, email, datetime, no_of_people, special_request)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            booking.user_id,
            booking.name,
            booking.email,
            booking.datetime,
            booking.no_of_people,
            booking.special_request,
        )
        return {"message": "Table booked successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await app.state.db_pool.release(conn)


@app.get("/get-bookings/{user_id}")
async def get_bookings(user_id: str):
    conn = app.state.db_pool

    bookings = await conn.fetch("SELECT * FROM bookings WHERE user_id = $1", user_id)
    if not bookings:
        raise HTTPException(status_code=404, detail="No bookings found for this user.")

    return {
        "user_id": user_id,
        "bookings": [
            {
                "name": booking["name"],
                "email": booking["email"],
                "datetime": booking["datetime"],
                "no_of_people": booking["no_of_people"],
                "special_request": booking["special_request"]
            } for booking in bookings
        ]
    }


# Contact Us Route

@app.post("/contact-us/")
async def contact_us(contact: ContactUsInput):
    conn = app.state.db_pool

    await conn.execute(
        """
        INSERT INTO contact_us (name, email, subject, message)
        VALUES ($1, $2, $3, $4)
        """,
        contact.name,
        contact.email,
        contact.subject,
        contact.message,
    )
    return {"message": "Thank you for reaching out to us. We will get back to you soon!"}


# Admin Routes for Events

@app.post("/admin/add-event/")
async def add_event(
    name: str,
    description: str,
    price: float,
    pic: UploadFile = File(...)
):
    conn = app.state.db_pool

    try:
        # Save the image file to the upload directory
        file_location = UPLOAD_DIR / pic.filename
        with file_location.open("wb") as buffer:
            buffer.write(await pic.read())

        # Insert event details into the database
        await conn.execute(
            """
            INSERT INTO events (pic_path, name, description, price)
            VALUES ($1, $2, $3, $4)
            """,
            str(file_location), name, description, price
        )
        return {"message": "Event added successfully!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@app.get("/admin/get-all-events/")
async def get_all_events():
    conn = app.state.db_pool

    try:
        events = await conn.fetch("SELECT * FROM events")
        if not events:
            raise HTTPException(status_code=404, detail="No events found.")

        return {
            "events": [
                {
                    "id": event["id"],
                    "pic_path": event["pic_path"],
                    "name": event["name"],
                    "description": event["description"],
                    "price": event["price"],
                    "created_at": event["created_at"]
                } for event in events
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


# Admin Routes for Services

@app.post("/admin/add-service/")
async def add_service(
    name: str,
    description: str,
    image: UploadFile = File(...)
):
    conn = app.state.db_pool

    try:
        # Save the image file to the upload directory
        file_location = UPLOAD_DIR / image.filename
        with file_location.open("wb") as buffer:
            buffer.write(await image.read())

        # Insert service details into the database
        await conn.execute(
            """
            INSERT INTO services (image_path, name, description)
            VALUES ($1, $2, $3)
            """,
            str(file_location), name, description
        )
        return {"message": "Service added successfully!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@app.get("/admin/get-all-services/")
async def get_all_services():
    conn = app.state.db_pool

    try:
        services = await conn.fetch("SELECT * FROM services")
        if not services:
            raise HTTPException(status_code=404, detail="No services found.")

        return {
            "services": [
                {
                    "id": service["id"],
                    "image_path": service["image_path"],
                    "name": service["name"],
                    "description": service["description"],
                    "created_at": service["created_at"]
                } for service in services
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


# Admin Routes for Team Members

@app.post("/admin/add-team-member/")
async def add_team_member(
    name: str,
    designation: str,
    description: str,
    image: UploadFile = File(...)
):
    conn = app.state.db_pool

    try:
        # Save the image file to the upload directory
        file_location = UPLOAD_DIR / image.filename
        with file_location.open("wb") as buffer:
            buffer.write(await image.read())

        # Insert team member details into the database
        await conn.execute(
            """
            INSERT INTO team_members (image_path, name, designation, description)
            VALUES ($1, $2, $3, $4)
            """,
            str(file_location), name, designation, description
        )
        return {"message": "Team member added successfully!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@app.get("/admin/get-all-team-members/")
async def get_all_team_members():
    conn = app.state.db_pool

    try:
        team_members = await conn.fetch("SELECT * FROM team_members")
        if not team_members:
            raise HTTPException(status_code=404, detail="No team members found.")

        return {
            "team_members": [
                {
                    "id": member["id"],
                    "image_path": member["image_path"],
                    "name": member["name"],
                    "designation": member["designation"],
                    "description": member["description"],
                    "created_at": member["created_at"]
                } for member in team_members
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

# Admin Route to Delete a Team Member by ID
@app.delete("/admin/delete-team-member/{id}/")
async def delete_team_member(id: int):
    conn = app.state.db_pool

    try:
        # Delete the team member from the database
        result = await conn.execute("DELETE FROM team_members WHERE id = $1", id)

        if result == "DELETE 0":  # If no rows were deleted
            raise HTTPException(status_code=404, detail="Team member not found.")

        return {"message": "Team member deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


# Admin Route to Delete an Event by ID
@app.delete("/admin/delete-event/{id}/")
async def delete_event(id: int):
    conn = app.state.db_pool

    try:
        # Delete the event from the database
        result = await conn.execute("DELETE FROM events WHERE id = $1", id)

        if result == "DELETE 0":  # If no rows were deleted
            raise HTTPException(status_code=404, detail="Event not found.")

        return {"message": "Event deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


# Admin Route to Delete a Service by ID
@app.delete("/admin/delete-service/{id}/")
async def delete_service(id: int):
    conn = app.state.db_pool

    try:
        # Delete the service from the database
        result = await conn.execute("DELETE FROM services WHERE id = $1", id)

        if result == "DELETE 0":  # If no rows were deleted
            raise HTTPException(status_code=404, detail="Service not found.")

        return {"message": "Service deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")
CREATE TABLE authors (
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(80) NOT NULL,
    last_name VARCHAR(80) NOT NULL,
    email VARCHAR(200) UNIQUE,
    country VARCHAR(100),
    born_on DATE
);

CREATE TABLE books (
    id SERIAL PRIMARY KEY,
    author_id INTEGER NOT NULL REFERENCES authors(id),
    title VARCHAR(240) NOT NULL,
    isbn VARCHAR(13) NOT NULL UNIQUE,
    published_on DATE,
    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    description TEXT
);

CREATE TABLE members (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(160) NOT NULL,
    email VARCHAR(200) NOT NULL UNIQUE,
    joined_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE loans (
    id BIGSERIAL PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id),
    member_id INTEGER NOT NULL REFERENCES members(id),
    borrowed_on DATE NOT NULL,
    returned_on DATE,
    UNIQUE (book_id, member_id, borrowed_on)
);


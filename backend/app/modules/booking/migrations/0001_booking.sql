-- 只放會議室、設備、公務車這類東西，不放人（人在 org 模組的 employees）
CREATE TABLE resources (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL UNIQUE,
  kind text NOT NULL CHECK (kind IN ('room', 'equipment', 'vehicle')),
  location text NULL,
  capacity int NULL CHECK (capacity > 0),
  features text[] NOT NULL DEFAULT '{}',
  is_active boolean NOT NULL DEFAULT true,
  note text NULL
);

CREATE TABLE bookings (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  title text NOT NULL CHECK (btrim(title) <> ''),
  category text NOT NULL,
  start_at timestamp NOT NULL,
  end_at timestamp NOT NULL,
  status text NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled')),
  note text NULL,
  created_by int NOT NULL REFERENCES users (id),
  created_at timestamp NOT NULL DEFAULT now(),
  CHECK (end_at > start_at)
);

CREATE INDEX bookings_start_at_idx ON bookings (start_at);

-- during、is_active 是從 bookings 複製過來的：排除限制只能比較同一張表的欄位。
-- 同步由下面兩個 trigger 負責，應用程式不需要、也不應該自己寫這兩個欄位
CREATE TABLE booking_resources (
  booking_id int NOT NULL REFERENCES bookings (id) ON DELETE CASCADE,
  resource_id int NOT NULL REFERENCES resources (id),
  during tsrange NOT NULL,
  is_active boolean NOT NULL,
  PRIMARY KEY (booking_id, resource_id),
  -- 同一個資源、時間重疊、都還有效的兩列不能同時存在；由資料庫保證，並行的兩個請求也一樣
  EXCLUDE USING gist (resource_id WITH =, during WITH &&) WHERE (is_active)
);

CREATE TABLE booking_participants (
  booking_id int NOT NULL REFERENCES bookings (id) ON DELETE CASCADE,
  employee_id int NOT NULL REFERENCES employees (id),
  role text NOT NULL CHECK (role IN ('organizer', 'attendee')),
  PRIMARY KEY (booking_id, employee_id)
);

CREATE INDEX booking_participants_employee_idx ON booking_participants (employee_id);

-- 資料庫只保證「至多一個」主辦人；「至少一個」由 service 在建立時保證
CREATE UNIQUE INDEX booking_participants_one_organizer_idx ON booking_participants (booking_id) WHERE role = 'organizer';

CREATE FUNCTION booking_resources_fill() RETURNS trigger AS $$
BEGIN
  SELECT tsrange(b.start_at, b.end_at, '[)'), (b.status = 'confirmed')
    INTO NEW.during, NEW.is_active
    FROM bookings b WHERE b.id = NEW.booking_id;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER booking_resources_fill_trigger
  BEFORE INSERT ON booking_resources
  FOR EACH ROW EXECUTE FUNCTION booking_resources_fill();

CREATE FUNCTION bookings_sync_resources() RETURNS trigger AS $$
BEGIN
  UPDATE booking_resources
    SET during = tsrange(NEW.start_at, NEW.end_at, '[)'), is_active = (NEW.status = 'confirmed')
    WHERE booking_id = NEW.id;
  RETURN NULL;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER bookings_sync_resources_trigger
  AFTER UPDATE OF start_at, end_at, status ON bookings
  FOR EACH ROW EXECUTE FUNCTION bookings_sync_resources();

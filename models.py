from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)

    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    farms = relationship("Farm", back_populates="user", cascade="all, delete-orphan")
    disease_reports = relationship("DiseaseReport", back_populates="user", cascade="all, delete-orphan")
    satellite_reports = relationship("SatelliteReport", back_populates="user", cascade="all, delete-orphan")


class Farm(Base):
    __tablename__ = "farms"
    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    geometry_json = Column(Text, nullable=False)   # GeoJSON string
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="farms")


class DiseaseReport(Base):
    __tablename__ = "disease_reports"
    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    disease_name = Column(String, nullable=False)
    disease_key = Column(String, nullable=True)
    confidence = Column(String, nullable=True)  # store as string e.g. "92.3"
    image_path = Column(String, nullable=True)  # stored in uploads/

    # Optional explanation fields (if your model provides them)
    symptoms = Column(Text, nullable=True)
    cause = Column(Text, nullable=True)
    prevention = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="disease_reports")


class SatelliteReport(Base):
    __tablename__ = "satellite_reports"
    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    farm_name = Column(String, nullable=False)
    farm_id = Column(Integer, nullable=True)  # optional link if you want

    geometry_json = Column(Text, nullable=False)
    summary_json = Column(Text, nullable=False)     # {"ndvi":..,"ndmi":..,"evi":..}
    timeseries_json = Column(Text, nullable=False)  # list of points
    change_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="satellite_reports")
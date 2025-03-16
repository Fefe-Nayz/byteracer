"use client";
import { useState, useEffect, useRef } from "react";

export function useLocalStorage<T>(key: string, initialValue: T) {
  // Create a ref to track initialization
  const isInitialized = useRef(false);
  
  // State to store our value
  const [storedValue, setStoredValue] = useState<T>(initialValue);

  // Initialize from localStorage only once on mount
  useEffect(() => {
    // Skip if we've already initialized
    if (isInitialized.current) return;
    
    try {
      // Check if localStorage is available (to avoid SSR issues)
      if (typeof window !== "undefined") {
        const item = window.localStorage.getItem(key);
        if (item) {
          setStoredValue(JSON.parse(item));
        }
      }
    } catch (error) {
      console.error("Error reading localStorage:", error);
    }
    
    // Mark as initialized so we don't run this effect again
    isInitialized.current = true;
  }, [key]);

  // Return a wrapped version of useState's setter function
  // that persists the new value to localStorage
  const setValue = (value: T | ((val: T) => T)) => {
    try {
      // Allow value to be a function for previous state
      const valueToStore = value instanceof Function ? value(storedValue) : value;
      
      // Save state
      setStoredValue(valueToStore);
      
      // Save to localStorage
      if (typeof window !== "undefined") {
        window.localStorage.setItem(key, JSON.stringify(valueToStore));
      }
    } catch (error) {
      console.error("Error writing to localStorage:", error);
    }
  };

  return [storedValue, setValue] as const;
}
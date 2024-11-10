import { createSlice } from "@reduxjs/toolkit";
import { HYDRATE } from "next-redux-wrapper";

const initialState = {
  cik: "",
};

const cikSlice = createSlice({
  name: "cik",
  initialState,
  reducers: {
    setCik(state, action) {
    //?intitial state load 
      state.cik = action.payload;
    },
    [HYDRATE]: (state, action) => {
      return {
        ...state,
        ...action.payload,
      };
    },
  },
});

export const selectCik = (state) => state.filer.cik;

export const { setCik } = cikSlice.actions;

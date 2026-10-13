/** @type {import('tailwindcss').Config} */
export default {
  content: ['./frontend/**/*.{js,jsx}', './web/index.html'],
  theme: {
    extend: {
      fontFamily: { geist: ['Geist', 'sans-serif'] },
    },
  },
  plugins: [],
};

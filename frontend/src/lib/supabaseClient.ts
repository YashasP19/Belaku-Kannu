import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || '';

const isConfigured = Boolean(supabaseUrl && supabaseAnonKey);

if (!isConfigured) {
  console.warn(
    'Supabase URL or Anon Key is missing. Set NEXT_PUBLIC_SUPABASE_URL and ' +
      'NEXT_PUBLIC_SUPABASE_ANON_KEY (in frontend/.env.local, or in your hosting provider settings).'
  );
}

// createClient() throws if the URL is empty, which used to crash `next build`
// (and therefore the whole deployment) whenever the variables were not set.
// Fall back to harmless placeholders so the build and the pages still load;
// requests simply fail until the real variables are provided.
export const supabase = createClient(
  isConfigured ? supabaseUrl : 'https://placeholder.supabase.co',
  isConfigured ? supabaseAnonKey : 'placeholder-anon-key'
);

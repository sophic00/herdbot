def bdecode(data: bytes):
    """
    Decodes bencoded bytes data into Python objects.
    Strings are returned as bytes, dictionaries have string keys decoded as utf-8.
    """
    def decode_next(idx):
        if idx >= len(data):
            raise ValueError("Unexpected EOF while parsing bencode")
            
        char = data[idx:idx+1]
        if char == b'i':
            # Decode integer: i<integer>e
            idx += 1
            end = data.find(b'e', idx)
            if end == -1:
                raise ValueError("Unterminated integer in bencode")
            val = int(data[idx:end])
            return val, end + 1
        elif char == b'l':
            # Decode list: l<items>e
            idx += 1
            lst = []
            while idx < len(data) and data[idx:idx+1] != b'e':
                item, idx = decode_next(idx)
                lst.append(item)
            if idx >= len(data):
                raise ValueError("Unterminated list in bencode")
            return lst, idx + 1
        elif char == b'd':
            # Decode dictionary: d<keys_and_values>e
            idx += 1
            dct = {}
            while idx < len(data) and data[idx:idx+1] != b'e':
                key, idx = decode_next(idx)
                if not isinstance(key, bytes):
                    raise ValueError("Dictionary key must be a bencoded string")
                val, idx = decode_next(idx)
                dct[key.decode('utf-8', errors='ignore')] = val
            if idx >= len(data):
                raise ValueError("Unterminated dictionary in bencode")
            return dct, idx + 1
        elif char.isdigit():
            # Decode string: <length>:<string_data>
            colon = data.find(b':', idx)
            if colon == -1:
                raise ValueError("Unterminated string length in bencode")
            length = int(data[idx:colon])
            start = colon + 1
            end = start + length
            if end > len(data):
                raise ValueError("String length exceeds remaining data size")
            val = data[start:end]
            return val, end
        else:
            raise ValueError(f"Invalid bencode type prefix: {char}")

    val, _ = decode_next(0)
    return val

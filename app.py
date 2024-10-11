from flask import Flask, render_template, request, redirect, make_response, flash
import sqlite3
from datetime import datetime
import csv
from io import BytesIO  # Word dosyası için BytesIO kullanıyoruz
import locale
from docx import Document  # python-docx ile Word dosyası oluşturma

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Flash mesajları için gizli anahtar

# Türkçe tarih formatı için locale ayarı
locale.setlocale(locale.LC_TIME, 'tr_TR.UTF-8')

# Veritabanı bağlantısı ve tabloların oluşturulması
def connect_db():
    conn = sqlite3.connect('budget.db')
    conn.row_factory = sqlite3.Row
    return conn

# Veritabanını başlatma ve tabloları oluşturma
def init_db():
    with connect_db() as conn:
        # Harcamalar için transactions tablosu
        conn.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY,
            description TEXT,
            amount REAL,
            date TEXT,
            type_id INTEGER,
            FOREIGN KEY(type_id) REFERENCES expense_types(id)
        )''')

        # Harcama türlerini eklemek için expense_types tablosu
        conn.execute('''
        CREATE TABLE IF NOT EXISTS expense_types (
            id INTEGER PRIMARY KEY,
            type_name TEXT UNIQUE
        )''')

        # Bakiyeyi tutmak için balance tablosu
        conn.execute('''
        CREATE TABLE IF NOT EXISTS balance (
            id INTEGER PRIMARY KEY,
            total REAL DEFAULT 0
        )''')

        if conn.execute('SELECT COUNT(*) FROM balance').fetchone()[0] == 0:
            conn.execute('INSERT INTO balance (id, total) VALUES (1, 0)')
        
        conn.commit()

# Ana sayfa
@app.route('/')
def index():
    conn = connect_db()
    types = conn.execute('SELECT * FROM expense_types').fetchall()
    transactions = conn.execute('''
        SELECT t.*, e.type_name 
        FROM transactions t
        LEFT JOIN expense_types e ON t.type_id = e.id
        ORDER BY t.date DESC LIMIT 10
    ''').fetchall()
    balance = conn.execute('SELECT total FROM balance WHERE id = 1').fetchone()['total']
    conn.close()

    formatted_transactions = [{
        'id': txn['id'],
        'description': txn['description'],
        'amount': "{:+,.2f}".format(float(txn['amount'])),
        'date': datetime.strptime(txn['date'], '%Y-%m-%d').strftime('%d %B %Y'),
        'type_name': txn['type_name'],
        'class': 'positive' if txn['amount'] >= 0 else 'negative'
    } for txn in transactions]

    return render_template('index.html', balance="{:,.2f}".format(balance), transactions=formatted_transactions, types=types)

# Harcama raporu sayfası
@app.route('/report')
def report():
    conn = connect_db()
    report_data = conn.execute('''
        SELECT e.type_name, SUM(t.amount) as total_amount
        FROM transactions t
        LEFT JOIN expense_types e ON t.type_id = e.id
        GROUP BY e.type_name
        HAVING total_amount < 0
    ''').fetchall()
    conn.close()

    # Rapor verilerini float olarak formatla ve pozitif hale getir
    formatted_report = [{
        'type_name': row['type_name'],
        'total_amount': abs(float(row['total_amount']))  # Negatif değerleri pozitif yapıyoruz
    } for row in report_data]

    return render_template('report.html', report_data=formatted_report)

# Anapara ekleme
@app.route('/add_funds', methods=['POST'])
def add_funds():
    description = request.form['description']
    amount = float(request.form['amount'])
    date = request.form['date']
    type_id = request.form['type_id']

    conn = connect_db()
    conn.execute('INSERT INTO transactions (description, amount, date, type_id) VALUES (?, ?, ?, ?)', (description, amount, date, type_id))
    conn.execute('UPDATE balance SET total = total + ? WHERE id = 1', (amount,))
    conn.commit()
    conn.close()

    return redirect('/')

# Harcama ekleme
@app.route('/add_expense', methods=['POST'])
def add_expense():
    description = request.form['description']
    amount = -abs(float(request.form['amount']))  # Harcama negatif olarak kaydedilir
    date = request.form['date']
    type_id = request.form['type_id']

    conn = connect_db()
    conn.execute('INSERT INTO transactions (description, amount, date, type_id) VALUES (?, ?, ?, ?)', (description, amount, date, type_id))
    conn.execute('UPDATE balance SET total = total + ? WHERE id = 1', (amount,))
    conn.commit()
    conn.close()

    return redirect('/')

# CSV Dışa Aktarma İşlevi
@app.route('/export_csv')
def export_csv():
    conn = connect_db()
    transactions = conn.execute('''
        SELECT t.*, e.type_name
        FROM transactions t
        LEFT JOIN expense_types e ON t.type_id = e.id
        ORDER BY t.date DESC
    ''').fetchall()
    conn.close()

    si = StringIO()
    cw = csv.writer(si)

    # UTF-8 ile BOM eklemek (Excel'de Türkçe karakterlerin doğru görüntülenmesi için)
    si.write('\ufeff')

    # CSV Başlıkları
    cw.writerow(['ID', 'Açıklama', 'Miktar (TL)', 'Tarih', 'Tür'])

    # Her işlemi ayrı sütunlara yaz
    for txn in transactions:
        formatted_amount = "{:+,.2f}".format(float(txn['amount']))  # Miktarı iki ondalık basamakla formatla
        formatted_date = datetime.strptime(txn['date'], '%Y-%m-%d').strftime('%d-%m-%Y')  # Tarihi dd-mm-yyyy formatına çevir
        cw.writerow([txn['id'], txn['description'], formatted_amount, formatted_date, txn['type_name']])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=transactions.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output

# Harcama raporunu Word formatında dışa aktarma
@app.route('/export_word')
def export_word():
    conn = connect_db()
    report_data = conn.execute('''
        SELECT e.type_name, SUM(t.amount) as total_amount
        FROM transactions t
        LEFT JOIN expense_types e ON t.type_id = e.id
        GROUP BY e.type_name
        HAVING total_amount < 0
    ''').fetchall()
    conn.close()

    # Word dokümanı oluşturma
    doc = Document()
    doc.add_heading('Harcama Raporu', 0)

    # Tablo ekliyoruz
    table = doc.add_table(rows=1, cols=2)
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = 'Harcama Türü'
    hdr_cells[1].text = 'Toplam Harcama (TL)'

    # Verileri tabloya ekleme
    for row in report_data:
        row_cells = table.add_row().cells
        row_cells[0].text = row['type_name']
        row_cells[1].text = "{:,.2f}".format(abs(float(row['total_amount']))) + ' TL'

    # Word dokümanını response olarak döndürüyoruz
    f = BytesIO()  # BytesIO kullanıyoruz
    doc.save(f)  # Dosyayı bellekte kaydediyoruz
    f.seek(0)
    
    response = make_response(f.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=harcama_raporu.docx'
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    
    return response

# İşlem silme
@app.route('/delete_transaction/<int:transaction_id>', methods=['POST'])
def delete_transaction(transaction_id):
    conn = connect_db()
    transaction = conn.execute('SELECT amount FROM transactions WHERE id = ?', (transaction_id,)).fetchone()

    if transaction:
        amount = transaction['amount']
        conn.execute('DELETE FROM transactions WHERE id = ?', (transaction_id,))
        conn.execute('UPDATE balance SET total = total - ? WHERE id = 1', (amount,))
        conn.commit()

    conn.close()
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)

